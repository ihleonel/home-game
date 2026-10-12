from django.urls import path

from . import catalog_views, views

urlpatterns = [
    path('games/', catalog_views.game_catalog, name='game-catalog'),
    path('matches/', views.start_match_view, name='start-match'),
    path('matches/<uuid:match_ref>/', views.match_detail_view, name='match-detail'),
    path(
        'matches/<uuid:match_ref>/actions/',
        views.submit_action_view,
        name='submit-action',
    ),
]
