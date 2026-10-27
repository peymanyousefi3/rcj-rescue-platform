from django.db import migrations

def protect_audit(apps,schema_editor):
    if schema_editor.connection.vendor!='postgresql': return
    schema_editor.execute('''CREATE FUNCTION arena_audit_append_only() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Audit events are append-only'; END;
        $$ LANGUAGE plpgsql''')
    schema_editor.execute('''CREATE TRIGGER arena_audit_no_edit
        BEFORE UPDATE OR DELETE ON arena_auditevent
        FOR EACH ROW EXECUTE FUNCTION arena_audit_append_only()''')

def remove_protection(apps,schema_editor):
    if schema_editor.connection.vendor!='postgresql': return
    schema_editor.execute('DROP TRIGGER IF EXISTS arena_audit_no_edit ON arena_auditevent')
    schema_editor.execute('DROP FUNCTION IF EXISTS arena_audit_append_only()')

class Migration(migrations.Migration):
    dependencies=[('arena','0001_initial')]
    operations=[migrations.RunPython(protect_audit,remove_protection)]
