"""Move the single vote target into the new target relation (S5).

The relation table lands first (``0007``) and the ``target`` column is removed
afterwards (``0009``), so this data migration runs while both shapes exist. It
copies every existing vote's single target into exactly one relation row, which
is what makes the batch contract lossless for the rows written before it.
"""

from django.db import migrations


def move_targets(apps, schema_editor):
    vote_model = apps.get_model('rooms', 'ExpulsionVote')
    target_model = apps.get_model('rooms', 'ExpulsionVoteTarget')
    database = schema_editor.connection.alias
    rows = (
        vote_model.objects.using(database)
        .exclude(target_id=None)
        .values_list('pk', 'target_id')
    )
    target_model.objects.using(database).bulk_create(
        [
            target_model(vote_id=vote_id, participant_id=target_id)
            for vote_id, target_id in rows
        ],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ('rooms', '0007_expulsionvotetarget'),
    ]

    operations = [
        migrations.RunPython(move_targets, migrations.RunPython.noop),
    ]
