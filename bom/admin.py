from django.contrib import admin
from django.contrib.contenttypes.admin import GenericStackedInline
from simple_history.admin import SimpleHistoryAdmin

from bom import models


class AttachmentInlines(GenericStackedInline):
    model = models.Attachment
    exclude = ()
    extra = 1


class PartSourceAdmin(admin.TabularInline):
    model = models.PartSource
    extra = 1
    fk_name = 'part'


class NamedPieceInline(admin.TabularInline):
    model = models.NamedPiece
    extra = 1
    fk_name = 'part'


class SubAssemblyLineAdmin(admin.TabularInline):
    model = models.SubAssemblyLineItem
    extra = 1
    fk_name = 'subassembly'


class PartAdmin(SimpleHistoryAdmin):
    inlines = [PartSourceAdmin, NamedPieceInline, AttachmentInlines]


class NamedPieceAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'part', 'suffix', 'note')
    search_fields = ('part__reference', 'suffix', 'note')
    inlines = [AttachmentInlines]


class SubAssemblyAdmin(SimpleHistoryAdmin):
    inlines = [SubAssemblyLineAdmin, AttachmentInlines]


class FeedbackAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'author', 'created', 'resolved', 'resolved_by')
    list_filter = ('content_type',)
    search_fields = ('text',)


class PCBPartAdmin(admin.ModelAdmin):
    list_display = ('reference', 'name', 'LCSCPartNo', 'Footprint', 'Value', 'Category', 'DatasheetLink', 'team')
    search_fields = ('reference', 'name', 'LCSCPartNo', 'Footprint', 'Value', 'Category', 'DatasheetLink')
    list_filter = ('team',)
    readonly_fields = ('created', 'updated')


class TeamAdmin(admin.ModelAdmin):
    model = models.Team


admin.site.register(models.Part, PartAdmin)
admin.site.register(models.PCBPart, PCBPartAdmin)
admin.site.register(models.NamedPiece, NamedPieceAdmin)
admin.site.register(models.SubAssembly, SubAssemblyAdmin)
admin.site.register(models.Team, TeamAdmin)
admin.site.register(models.Feedback, FeedbackAdmin)
