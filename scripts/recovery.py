"""Encrypted, coordinated backups and restoration into NEW isolated projects only.

Requires Docker Compose and the official age CLI. Never prints backup contents or secrets.
"""
import argparse
import fcntl
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    return subprocess.run(command,check=True,stderr=subprocess.PIPE,**kwargs)  # nosec B603


def compose(project, env, *args, **kwargs):
    return run(['docker','compose','--project-name',project,'--env-file',str(env),'-f',str(ROOT/'compose.yaml'),*args],**kwargs)


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(1024**2),b''):value.update(chunk)
    return value.hexdigest()


def check_new_project(project):
    if not re.fullmatch(r'rcj-restore-[a-z0-9-]{1,40}',project):
        raise ValueError('Restoration requires a new rcj-restore-... project name.')
    for resource in ['container','volume','network']:
        result=run(['docker',resource,'ls','--filter','label=com.docker.compose.project='+project,'--quiet'],stdout=subprocess.PIPE)
        if result.stdout.strip():raise ValueError('That restore project already has resources; refusing to overwrite it.')


def backup(args):
    if not args.confirm_maintenance:raise ValueError('Backup briefly stops app/worker. Supply --confirm-maintenance in the scheduled maintenance window.')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}',args.project):raise ValueError('Invalid Compose project name.')
    env=Path(args.env).resolve()
    if not env.is_file():raise ValueError('Provide the private deployment environment file.')
    output=Path(args.output).resolve()
    if output.exists():raise ValueError('Backup destination already exists.')
    active=compose(args.project,env,'ps','--status','running','--services',stdout=subprocess.PIPE).stdout.decode().split()
    writers=[name for name in ['app','worker'] if name in active]
    output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(prefix='rcj-backup-',dir=args.temp_dir) as directory:
        stage=Path(directory);created=False
        try:
            if writers:compose(args.project,env,'stop','--timeout','180',*writers,stdout=subprocess.DEVNULL)
            with (stage/'database.dump').open('xb') as file:
                compose(args.project,env,'exec','-T','db','sh','-c','exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc',stdout=file)
            with (stage/'private.tar').open('xb') as file:
                compose(args.project,env,'run','--rm','--no-deps','-T','--entrypoint','tar','app','--exclude=./.upload-tmp','-C','/app/var/private','-cf','-','.',stdout=file)
            shutil.copyfile(env,stage/'config.env');os.chmod(stage/'config.env',0o600)
            commit=run(['git','-C',str(ROOT),'rev-parse','HEAD'],stdout=subprocess.PIPE).stdout.decode().strip()
            manifest={'commit':commit,'files':{name:digest(stage/name) for name in ['database.dump','private.tar','config.env']}}
            (stage/'manifest.json').write_text(json.dumps(manifest))
            with output.open('xb') as encrypted:
                created=True
                age=subprocess.Popen(['age','-r',args.recipient],stdin=subprocess.PIPE,stdout=encrypted,stderr=subprocess.PIPE)
                try:
                    with tarfile.open(fileobj=age.stdin,mode='w|') as archive:
                        for name in [*manifest['files'],'manifest.json']:archive.add(stage/name,arcname=name,recursive=False)
                    age.stdin.close();age.wait(timeout=120)
                    if age.returncode:raise ValueError('Encryption failed; check the age recipient.')
                finally:
                    if age.poll() is None:age.kill();age.wait()
            print('Encrypted backup created:',output)
        except Exception:
            if created:output.unlink(missing_ok=True)
            raise
        finally:
            if writers:compose(args.project,env,'start',*writers,stdout=subprocess.DEVNULL)


def restore(args):
    check_new_project(args.project)
    destination=Path(args.destination).resolve()
    if destination.exists():raise ValueError('Restore destination must not exist.')
    expected={'database.dump','private.tar','config.env','manifest.json'}
    with tempfile.TemporaryDirectory(prefix='rcj-restore-',dir=args.temp_dir) as directory:
        stage=Path(directory)
        with (stage/'archive.tar').open('xb') as file:
            run(['age','-d','-i',str(Path(args.identity).resolve()),str(Path(args.backup).resolve())],stdout=file)
        total=0;seen=set()
        with tarfile.open(stage/'archive.tar','r:') as archive:
            for member in archive:
                if member.name not in expected or member.name in seen or not member.isfile():raise ValueError('Unexpected backup member.')
                seen.add(member.name);total+=member.size
                if total>args.max_bytes:raise ValueError('Restore exceeds the configured size budget.')
                with archive.extractfile(member) as source,(stage/member.name).open('xb') as target:shutil.copyfileobj(source,target)
        if seen!=expected:raise ValueError('Incomplete backup.')
        manifest=json.loads((stage/'manifest.json').read_text())
        if set(manifest['files'])!=expected-{'manifest.json'}:raise ValueError('Invalid backup manifest.')
        for name,value in manifest['files'].items():
            if digest(stage/name)!=value:raise ValueError('Backup integrity verification failed.')
        commit=run(['git','-C',str(ROOT),'rev-parse','HEAD'],stdout=subprocess.PIPE).stdout.decode().strip()
        if manifest['commit']!=commit:raise ValueError('Check out the source commit recorded in this backup before restoring it.')
        with tarfile.open(stage/'private.tar','r:') as archive:
            size=0
            for member in archive:
                path=PurePosixPath(member.name);size+=member.size
                if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()) or size>args.max_bytes:
                    raise ValueError('Unsafe private-storage archive.')
        check_new_project(args.project)
        destination.mkdir(mode=0o700,parents=True)
        env=destination/'.env';shutil.copyfile(stage/'config.env',env);os.chmod(env,0o600)
        compose(args.project,env,'up','-d','--wait','db',stdout=subprocess.DEVNULL)
        with (stage/'database.dump').open('rb') as file:
            compose(args.project,env,'exec','-T','db','sh','-c','exec pg_restore --no-owner --no-acl --clean --if-exists --exit-on-error -U "$POSTGRES_USER" -d "$POSTGRES_DB"',stdin=file,stdout=subprocess.DEVNULL)
        grants='GRANT USAGE ON SCHEMA public TO arena_app; GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO arena_app; GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO arena_app;'
        compose(args.project,env,'exec','-T','db','sh','-c','exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"','sh',grants,stdout=subprocess.DEVNULL)
        with (stage/'private.tar').open('rb') as file:
            compose(args.project,env,'run','--rm','--no-deps','-T','--entrypoint','tar','app','--no-same-owner','-C','/app/var/private','-xf','-',stdin=file,stdout=subprocess.DEVNULL)
        print('Restored into isolated project:',args.project)
        print('Application and mail worker were NOT started. Verify the restored environment before use.')


@contextmanager
def operation_lock(project):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}',project):raise ValueError('Invalid Compose project name.')
    directory=Path(tempfile.gettempdir())/f'rcj-recovery-locks-{os.getuid()}'
    directory.mkdir(mode=0o700,exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid!=os.getuid():raise ValueError('Unsafe recovery lock directory.')
    with (directory/(project+'.lock')).open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another recovery operation is using this project.') from None
        try:yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='mode',required=True)
    create=sub.add_parser('backup');create.add_argument('--project',required=True);create.add_argument('--env',default=str(ROOT/'.env'));create.add_argument('--output',required=True);create.add_argument('--recipient',required=True);create.add_argument('--confirm-maintenance',action='store_true')
    recover=sub.add_parser('restore');recover.add_argument('--project',required=True);recover.add_argument('--backup',required=True);recover.add_argument('--identity',required=True);recover.add_argument('--destination',required=True);recover.add_argument('--max-bytes',type=int,default=50*1024**3)
    for command in [create,recover]:command.add_argument('--temp-dir',help='Private encrypted filesystem with sufficient temporary space.')
    args=parser.parse_args()
    if not shutil.which('docker') or not shutil.which('age'):parser.error('Install Docker Compose and the official age CLI first.')
    try:
        with operation_lock(args.project):(backup if args.mode=='backup' else restore)(args)
    except (ValueError,OSError,subprocess.SubprocessError,tarfile.TarError) as exc:
        if isinstance(exc,ValueError):parser.error(str(exc))
        parser.error('Recovery operation failed. Review local service health and private operator logs; no backup contents were printed.')

if __name__=='__main__':main()
