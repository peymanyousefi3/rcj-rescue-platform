"""Export public pages only. Never export sessions, uploads, admin or team data."""
from pathlib import Path
from shutil import copytree
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.test import Client,override_settings

class Command(BaseCommand):
    help='Export a clearly labelled read-only public design preview.'
    def add_arguments(self,parser): parser.add_argument('--output',required=True,type=Path)
    def handle(self,*args,**options):
        output=options['output'];output.mkdir(parents=True,exist_ok=True)
        client=Client()
        with override_settings(ALLOWED_HOSTS=['testserver'],SECURE_SSL_REDIRECT=False):
            for section in ['', 'schedule','results','teams','maps','resources']:
                path='/'+section+'/' if section else '/'
                response=client.get(path)
                if response.status_code!=200: raise CommandError(f'Public page failed to render: {path}')
                html=response.content.decode()
                html=html.replace('<body>','<body><div class="preview-notice">DESIGN PREVIEW · Read-only public pages. Team login and private uploads run in the full local service.</div>')
                html=html.replace('href="/account/login/"','href="/preview-access/"').replace('href="/portal/"','href="/preview-access/"')
                html=html.replace('<script src="/static/arena/site.js" defer></script>','<script src="/static/arena/site.js" defer></script>')
                folder=output/section;folder.mkdir(parents=True,exist_ok=True)
                (folder/'index.html').write_text(html)
        copytree(settings.STATIC_ROOT,output/'static',dirs_exist_ok=True)
        folder=output/'preview-access';folder.mkdir(exist_ok=True)
        (folder/'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/arena/site.css"><title>Design preview · ASR 26</title><body><main class="centered"><section class="panel auth-card"><p class="eyebrow">DESIGN PREVIEW</p><h1>The full portal runs locally.</h1><p>This preview contains public pages only. Team authentication, uploads, confidential files and administration require the full application.</p><a class="button secondary" href="/">Back to competition centre ↗</a></section></main></body></html>')
        self.stdout.write('Exported public-only preview with explicit access limitations.')
