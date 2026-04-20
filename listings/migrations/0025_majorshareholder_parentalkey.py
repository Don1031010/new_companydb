import django.db.models.deletion
import modelcluster.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('listings', '0024_sharerecord_restructure'),
    ]

    operations = [
        migrations.AlterField(
            model_name='majorshareholder',
            name='share_record',
            field=modelcluster.fields.ParentalKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='entries',
                to='listings.sharerecord',
                verbose_name='スナップショット',
            ),
        ),
    ]
