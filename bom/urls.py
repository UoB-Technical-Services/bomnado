from django.urls import path, re_path

from bom import views
from bom.setup_views import FirstTimeSetupView, FirstTimeSetupAPIView, FirstTimeSetupCompleteView, FirstTimeSetupDemoView


app_name = 'bom'

urlpatterns = [

    # Note: Some URLS are hard-coded into the javascript. Search before refactoring.

    # First-time setup
    path('setup/', FirstTimeSetupView.as_view(), name='first_time_setup'),
    path('setup/api/', FirstTimeSetupAPIView.as_view(), name='first_time_setup_api'),
    path('setup/complete/', FirstTimeSetupCompleteView.as_view(), name='first_time_setup_complete'),
    path('setup/demo/', FirstTimeSetupDemoView.as_view(), name='first_time_setup_demo'),

    # Dashboard
    path('', views.DashboardView.as_view(), name='start'),

    # Teams
    path('teams/new', views.NewTeamView.as_view(), name='teams_create'),
    path('teams/', views.TeamsView.as_view(), name='teams'),
    re_path(r'^teams/(?P<pk>([0-9]+))/add', views.AddToTeamView.as_view(), name='teams_add'),
    re_path(r'^teams/(?P<pk>([0-9]+))/remove', views.RemoveFromTeamView.as_view(), name='teams_remove'),
    path('teams/<int:pk>/naming_guide', views.TeamNamingGuideView.as_view(), name='teams_naming_guide'),
    path('teams/<int:pk>/hs_lookup', views.TeamHsLookupView.as_view(), name='teams_hs_lookup'),
    path('teams/<int:pk>/hs_lookup', views.TeamHsLookupView.as_view(), name='teams_hs_lookup'),

    # User settings
    path('settings/', views.UserSettingsView.as_view(), name='user_settings'),
    path('settings/ai/test', views.ai_test_connection, name='ai_test_connection'),

    # The library (htmx fragments).
    path('library/parts/', views.library_parts, name='library_parts'),
    path('library/assemblies/', views.library_assemblies, name='library_assemblies'),
    path('library/search/', views.library_search, name='library_search'),

    # The AI chat window (htmx fragments) and the activity page.
    path('ai/chat/', views.ai_chat, name='ai_chat'),
    path('ai/chat/send', views.ai_chat_send, name='ai_chat_send'),
    path('ai/chat/<int:thread_id>/', views.ai_chat_status, name='ai_chat_status'),
    path('ai/chat/<int:thread_id>/stop', views.ai_chat_stop, name='ai_chat_stop'),
    path('ai/chat/<int:thread_id>/retry', views.ai_chat_retry, name='ai_chat_retry'),
    path('ai/chat/<int:thread_id>/delete', views.ai_chat_delete, name='ai_chat_delete'),
    path('ai/jobs/<int:job_id>/cancel', views.ai_job_cancel, name='ai_job_cancel'),
    path('ai/jobs/<int:job_id>/clear', views.ai_job_clear, name='ai_job_clear'),
    path('ai/jobs/', views.AIJobsView.as_view(), name='ai_jobs'),
    path('ai/jobs/clear', views.ai_jobs_clear, name='ai_jobs_clear'),

    path('export/backup', views.export_backup, name='export_backup'),
    path('backup/now', views.backup_now, name='backup_now'),

    # Parts
    re_path(r'^part/(?P<pk>([0-9]+))', views.PartEditorUpdateView, name='part_editor_update'),
    path('part/new', views.PartEditorCreateView.as_view(), name='part_editor_create'),
    path('part/start', views.PartStartView.as_view(), name='part_editor'),
    path('part/duplicate', views.PartDuplicateView.as_view(), name='part_duplicate'),

    # Assembly
    path('assembly/new', views.AssemblyEditorCreateView.as_view(), name='assembly_editor_create'),
    path('assembly', views.DashboardView.as_view(), name='assembly_editor'),
    path('assemblies', views.AssemblyStartView.as_view(), name='assembly_start'),

    re_path(r'^assembly/(?P<pk>([0-9]+))/export/xlsx', views.export_bom_as_xlsx, name='export_xlsx'),
    re_path(r'^assembly/(?P<pk>([0-9]+))/export/purchasing', views.export_purchasing, name='export_purchasing'),

    re_path(r'^assembly/(?P<pk>([0-9]+))/tools/production_phases', views.ToolProductionPhases.as_view(),
        name='tools_production_phases'),
    re_path(r'^assembly/(?P<pk>([0-9]+))/tools/orphan_finder', views.ToolOrphanFinder.as_view(),
        name='tools_orphan_finder'),
    re_path(r'^assembly/(?P<pk>([0-9]+))/tools/reviews', views.ToolReviews.as_view(), name='tools_reviews'),
    re_path(r'^assembly/(?P<pk>([0-9]+))/tools/sales_codes', views.ToolSalesCodes.as_view(),
        name='tools_sales_codes'),
    re_path(r'^assembly/(?P<pk>([0-9]+))/tools/deals/(?P<deal_id>([0-9]+))/update',
        views.ToolDealLineItemUpdateView.as_view(),
        name='tools_deals_update'),
    re_path(r'^assembly/(?P<pk>([0-9]+))/tools/deals/(?P<deal_id>([0-9]+))/edit', views.ToolDealUpdateView.as_view(),
        name='tools_deals_edit'),
    re_path(r'^assembly/(?P<pk>([0-9]+))/tools/deals/new', views.ToolDealCreateView.as_view(),
        name='tools_deals_create'),
    re_path(r'^assembly/(?P<pk>([0-9]+))/tools/deals', views.ToolDeals.as_view(),
        name='tools_deals'),

    # Line items (htmx fragments). Must precede the unanchored assembly editor pattern below.
    path('assembly/<int:pk>/line_items/add', views.assembly_line_item_add, name='assembly_line_item_add'),
    path('assembly/<int:pk>/line_items/<int:line_id>/delete', views.assembly_line_item_delete,
         name='assembly_line_item_delete'),

    re_path(r'^assembly/(?P<pk>([0-9]+))', views.AssemblyEditorUpdateView,
        name='assembly_editor_update'),
    re_path(r'^assembly/doc/(?P<pk>([0-9]+))', views.AssemblyDocumentationView.as_view(),
        name='assembly_documentation_view'),

    # Comments and activity (htmx fragments), for `part` or `subassembly`.
    path('activity/<str:model_name>/<int:pk>/', views.activity_entries, name='activity_entries'),
    path('activity/<str:model_name>/<int:pk>/feedback', views.feedback_add, name='feedback_add'),
    path('activity/<str:model_name>/<int:pk>/revert/<str:historical_model>/<int:history_id>',
         views.activity_revert, name='activity_revert'),
    path('feedback/<int:feedback_id>/resolve', views.feedback_resolve, name='feedback_resolve'),
    path('feedback/<int:feedback_id>/reopen', views.feedback_reopen, name='feedback_reopen'),

    # Attachments
    re_path(r'^attachment/attach/(?P<model_name>[\w\-]+)/(?P<model_pk>\d+)/$',
            views.attachment_attach,
            name='attachment_attach'),
    re_path(r'^attachment/delete/(?P<attachment_pk>\d+)/$', views.attachment_delete, name='attachment_delete'),
]
