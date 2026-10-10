from django.urls import path

from . import views

urlpatterns = [
    path('games/', views.game_catalog, name='game-catalog'),
    path('rooms/', views.create_room, name='create-room'),
    path('rooms/active/', views.active_room, name='active-room'),
    path('rooms/join/', views.join_room, name='join-room'),
    path('rooms/leave/', views.leave_room, name='leave-room'),
    path('rooms/ready/', views.update_ready_state, name='update-ready-state'),
]
