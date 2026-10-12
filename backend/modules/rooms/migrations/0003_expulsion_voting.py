import uuid

from django.db import migrations, models
import django.db.models.deletion


def populate_public_ids(apps, schema_editor):
    participant_model = apps.get_model('rooms', 'Participant')
    database = schema_editor.connection.alias
    for participant in participant_model.objects.using(database).filter(
        public_id__isnull=True
    ).only('pk').iterator():
        participant_model.objects.using(database).filter(pk=participant.pk).update(
            public_id=uuid.uuid4()
        )


class Migration(migrations.Migration):
    dependencies = [
        ('rooms', '0002_participant_presence'),
    ]

    operations = [
        migrations.AddField(
            model_name='participant',
            name='public_id',
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(
            code=populate_public_ids,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='participant',
            name='public_id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.CreateModel(
            name='ExpulsionVote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('cancelled', 'Cancelled')], default='pending', max_length=16)),
                ('resolution_reason', models.CharField(blank=True, default='', max_length=32)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('initiated_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='expulsion_votes_started', to='rooms.participant')),
                ('room', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='expulsion_votes', to='rooms.room')),
                ('target', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='expulsion_votes_as_target', to='rooms.participant')),
            ],
        ),
        migrations.CreateModel(
            name='ExpulsionBallot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('choice', models.CharField(blank=True, choices=[('yes', 'Yes'), ('no', 'No')], max_length=3, null=True)),
                ('cast_at', models.DateTimeField(blank=True, null=True)),
                ('vote', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ballots', to='rooms.expulsionvote')),
                ('voter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='expulsion_ballots', to='rooms.participant')),
            ],
        ),
        migrations.AddConstraint(
            model_name='expulsionvote',
            constraint=models.UniqueConstraint(condition=models.Q(('status', 'pending')), fields=('room',), name='one_pending_room_vote'),
        ),
        migrations.AddConstraint(
            model_name='expulsionballot',
            constraint=models.UniqueConstraint(fields=('vote', 'voter'), name='one_ballot_per_voter'),
        ),
    ]
