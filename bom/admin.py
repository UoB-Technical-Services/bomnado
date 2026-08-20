from django.contrib import admin
from django.contrib.contenttypes.admin import GenericStackedInline

from bom import models


class AttachmentInlines(GenericStackedInline):
    model = models.Attachment
    exclude = ()
    extra = 1


class PartSourceAdmin(admin.TabularInline):
    model = models.PartSource
    extra = 1
    fk_name = 'part'


class SubAssemblyLineAdmin(admin.TabularInline):
    model = models.SubAssemblyLineItem
    extra = 1
    fk_name = 'subassembly'


class PartAdmin(admin.ModelAdmin):
    inlines = [PartSourceAdmin, AttachmentInlines]


class SubAssemblyAdmin(admin.ModelAdmin):
    inlines = [SubAssemblyLineAdmin, AttachmentInlines]


class PCBPartAdmin(admin.ModelAdmin):
    list_display = ('reference', 'name', 'LCSCPartNo', 'Footprint', 'Value', 'Category', 'DatasheetLink', 'team')
    search_fields = ('reference', 'name', 'LCSCPartNo', 'Footprint', 'Value', 'Category', 'DatasheetLink')
    list_filter = ('team',)
    readonly_fields = ('created', 'updated')


class TeamAdmin(admin.ModelAdmin):
    model = models.Team


admin.site.register(models.Part, PartAdmin)
admin.site.register(models.PCBPart, PCBPartAdmin)
admin.site.register(models.SubAssembly, SubAssemblyAdmin)
admin.site.register(models.Team, TeamAdmin)
