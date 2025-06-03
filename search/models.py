from django.db import models


class Sites(models.Model):
    class_field = models.IntegerField(db_column='class')
    url = models.TextField()
    title = models.CharField(max_length=2048)
    keywords = models.TextField()
    first_par = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'sites'


class VisitedPageSet(models.Model):
    url = models.TextField()

    def __str__(self):
        return self.url


class UnVisitedPageSet(models.Model):
    url = models.TextField()

