"""Backfill the ``origin`` of votes written before the field existed (S6).

Migration ``0006_expulsionvote_origin_and_more`` added ``origin`` with
``default='automatic'`` and did not backfill, so every pre-existing row -- all
of them written by the manual endpoint, hence with a non-null ``initiated_by``
-- now reads ``origin='automatic'`` while carrying a caller, and the panel says
the vote opened on its own.

The default alone could not fix those rows: a column default applies only to
inserts that omit the field, and it must stay ``automatic`` because new sweep
votes keep getting their origin from it while the manual path keeps writing
``manual`` explicitly. So the historical rows are corrected here instead.

The update touches exactly the rows with a caller and is a single statement, so
re-running it is a no-op. There is no reverse: the previous value was the wrong
one, and the reverse of a backfill would be the corruption it fixes.
"""

from django.db import migrations


def backfill_manual_origin(apps, schema_editor):
    vote_model = apps.get_model('rooms', 'ExpulsionVote')
    database = schema_editor.connection.alias
    vote_model.objects.using(database).filter(
        initiated_by_id__isnull=False,
    ).exclude(origin='manual').update(origin='manual')


class Migration(migrations.Migration):
    dependencies = [
        ('rooms', '0009_remove_expulsionvote_target'),
    ]

    operations = [
        migrations.RunPython(backfill_manual_origin, migrations.RunPython.noop),
    ]
