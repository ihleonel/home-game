from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rooms', '0003_expulsion_voting'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='room',
            name='one_active_room',
        ),
        migrations.AddConstraint(
            model_name='room',
            constraint=models.UniqueConstraint(
                fields=('game_id', 'status'),
                condition=models.Q(status='active'),
                name='one_active_room_per_game',
            ),
        ),
    ]
