"""User-observable regressions for the calm companion experience."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from opencareyes.application.pet_pack_registry import PetPackRegistry
from opencareyes.application.status_presenter import StatusPresenter
from opencareyes.constants import PETS_DIR
from opencareyes.state import AppState, BreakState, GlobalPauseState, CapabilitiesState, EffectivePolicyState, FeatureRuntimeState
from opencareyes.ui.break_overlay import BreakOverlay
from opencareyes.ui.break_prompt import BreakPrompt
from opencareyes.ui.pet_animator import PetAnimator
from opencareyes.ui.pet_bubble import PetBubble
from opencareyes.ui.pet_surface import PetSurface
from opencareyes.ui.theme import ThemeManager, rest_palette
from opencareyes.ui.tray_icon import TrayIcon


def _luminance(hex_color):
    color = QColor(hex_color)
    channels = [color.redF(), color.greenF(), color.blueF()]
    channels = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return sum(c * weight for c, weight in zip(channels, (0.2126, 0.7152, 0.0722)))


@pytest.mark.parametrize('scene', ['gaze', 'snow_breathing', 'stretch', 'sleep'])
@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_rest_stays_dim_with_readable_text_in_both_app_themes(scene, theme):
    colors = rest_palette(SimpleNamespace(resolved=theme), scene)
    background = _luminance(colors['background'])
    assert background < 0.06
    for name in ('title', 'text', 'muted'):
        assert (_luminance(colors[name]) + 0.05) / (background + 0.05) >= 4.5


def test_escape_cancels_an_inflight_entrance_and_cannot_reopen_rest(qtbot):
    overlay = BreakOverlay()
    qtbot.addWidget(overlay)
    overlay.start_break(20, force=True)
    qtbot.keyClick(overlay, Qt.Key_Escape)
    qtbot.wait(560)
    assert not overlay.isVisible()
    assert not overlay._fallback_timer.isActive()
    assert all(not backdrop.isVisible() for backdrop in overlay._backdrops)


def test_reduced_motion_is_immediate_and_small_screen_keeps_exit_visible(qtbot):
    overlay = BreakOverlay()
    qtbot.addWidget(overlay)
    overlay.apply_theme(SimpleNamespace(resolved='light', motion_profile='reduced'))
    overlay.start_break(20)
    overlay.resize(640, 360)
    qtbot.wait(20)
    assert overlay.height() == 360
    assert overlay.windowOpacity() == 1.0
    assert overlay._scene_widget.isHidden()
    assert overlay.rect().contains(overlay._skip_button.geometry())
    assert overlay._skip_button.isVisible()
    overlay.end_break()


def test_repeated_rest_tick_does_not_restart_entrance(qtbot):
    overlay = BreakOverlay()
    qtbot.addWidget(overlay)
    overlay.start_break(20)
    qtbot.wait(60)
    before = overlay._entrance.animation.currentTime()
    overlay._on_break_tick(19, 20)
    assert overlay._entrance.animation.currentTime() >= before
    overlay.end_break()


def test_prompt_hide_cancels_animation_and_keeps_no_keyboard_activation(qtbot):
    prompt = BreakPrompt()
    qtbot.addWidget(prompt)
    prompt.show_prompt()
    assert prompt.testAttribute(Qt.WA_ShowWithoutActivating)
    prompt._skip_break()
    qtbot.wait(360)
    assert not prompt.isVisible()


def test_finishing_an_action_keeps_the_next_animation_clock_running(qtbot):
    clock = [0.0]
    animator = PetAnimator(clock=lambda: clock[0])
    image = QImage(8, 8, QImage.Format_RGBA8888)
    image.fill(Qt.white)
    frames = tuple(SimpleNamespace(image=image, duration_ms=50) for _ in range(2))
    click = SimpleNamespace(action_id='click', frames=frames, loop=False)
    idle = SimpleNamespace(action_id='idle', frames=frames, loop=True)
    animator.animation_finished.connect(lambda _action: animator.play('idle', idle))
    animator.set_surface_visible(True)
    animator.play('click', click)
    clock[0] = 0.11
    animator._advance()
    assert animator.action_id == 'idle'
    assert animator.is_running
    clock[0] = 0.17
    animator._advance()
    assert animator.frame_index == 1
    animator.set_surface_visible(False)


def test_registered_walk_has_real_intermediate_poses_and_safe_margins(qtbot):
    pack = PetPackRegistry(PETS_DIR).load('snow_ferret')
    frames = pack.actions['move'].frames
    assert len(frames) >= 12
    images = []
    bounds = []
    for frame in frames:
        image = QImage(str(Path(PETS_DIR) / 'snow_ferret' / frame.path)).copy(*frame.source_rect)
        images.append(bytes(image.convertToFormat(QImage.Format_RGBA8888).constBits()))
        # Raw alpha outside the safe frame margin must stay transparent.
        assert all(image.pixelColor(x, y).alpha() == 0 for x, y in ((0, 0), (383, 0), (0, 383), (383, 383)))
        from PIL import Image
        alpha = Image.frombytes('RGBA', (384, 384), images[-1]).getchannel('A')
        bounds.append(alpha.point(lambda a: 255 if a > 64 else 0).getbbox())
    assert len(set(images)) == len(frames)
    heights = [bottom - top for left, top, right, bottom in bounds]
    assert max(heights) - min(heights) < 18
    assert all(60 <= frame.duration_ms <= 85 for frame in frames)


def test_gaze_animation_uses_directional_clip_and_outfits_keep_fallback(qtbot):
    pack = PetPackRegistry(PETS_DIR).load('snow_ferret')
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack(pack.pet_id, pack)
    surface.set_gaze_direction('left')
    assert len(surface._action('look_cursor').frames) >= 5
    surface.set_outfit('navy_scarf')
    assert len(surface._action('look_cursor').frames) == 1


def test_manual_interaction_is_available_from_keyboard_bubble(qtbot):
    bubble = PetBubble()
    qtbot.addWidget(bubble)
    received = []
    bubble.interaction_requested.connect(received.append)
    actions = bubble._interact.menu().actions()
    assert [action.text() for action in actions] == ['摸摸头', '玩一会儿', '伸个懒腰', '打个招呼']
    actions[1].trigger()
    assert received == ['item.play']
    bubble._set_mode('rest_prompt')
    assert bubble._interact.isHidden()


def test_paused_or_already_resting_home_cannot_start_another_rest():
    working = AppState(breaks=BreakState(enabled=True, phase='working'),
                       capabilities=CapabilitiesState(breaks_available=True),
                       effective_policy=EffectivePolicyState(breaks=FeatureRuntimeState(True, True)))
    assert StatusPresenter.project(working).can_start_rest
    assert not StatusPresenter.project(replace(working, global_pause=GlobalPauseState(active=True))).can_start_rest
    assert not StatusPresenter.project(replace(working, breaks=replace(working.breaks, phase='resting'))).can_start_rest


def test_taskbar_theme_is_independent_of_application_theme(qtbot):
    manager = ThemeManager(theme_detector=lambda: 'light', taskbar_detector=lambda: 'dark')
    snapshot = manager.snapshot
    assert snapshot.resolved == 'light'
    assert snapshot.taskbar_resolved == 'dark'
    tray = TrayIcon.__new__(TrayIcon)
    # Test the real icon projection without constructing unrelated menu services.
    from PySide6.QtWidgets import QSystemTrayIcon
    QSystemTrayIcon.__init__(tray)
    tray._paused = False
    tray._icon_signature = None
    tray.apply_theme(snapshot)
    first = tray.icon().pixmap(32).toImage()
    tray.apply_theme(replace(snapshot, taskbar_resolved='light'))
    second = tray.icon().pixmap(32).toImage()
    assert first != second
    tray.apply_theme(snapshot, paused=True)
    assert tray.icon().pixmap(32).toImage() != first
    tray.deleteLater()


def test_async_clip_load_holds_pose_and_starts_clock_after_ready(qtbot):
    from PySide6.QtCore import QObject, Signal

    class DelayedRepository(QObject):
        resource_ready = Signal(str, str)
        resource_failed = Signal(str, str)

        def __init__(self):
            super().__init__()
            self.ready = False

        def load_frame(self, _pet_id, _path):
            return image if self.ready else None

    image = QImage(8, 8, QImage.Format_RGBA8888)
    image.fill(Qt.green)
    repo = DelayedRepository()
    animator = PetAnimator(repo)
    animator.set_pack('snow_ferret', None)
    animator.set_surface_visible(True)
    published = []
    animator.frame_changed.connect(published.append)
    direct = SimpleNamespace(action_id='idle', loop=True,
                             frames=(SimpleNamespace(image=image, duration_ms=500),))
    animator.play('idle', direct)
    clip = SimpleNamespace(action_id='play', loop=False, frames=tuple(
        SimpleNamespace(path='sprites/delayed.png', duration_ms=60) for _ in range(3)))
    animator.play('play', clip)
    qtbot.wait(210)
    assert len(published) == 1 and published[0] == image
    assert animator.frame_index == 0 and not animator.is_running
    repo.ready = True
    repo.resource_ready.emit('snow_ferret', 'sprites/delayed.png')
    assert len(published) == 2 and animator.is_running
    assert animator.frame_index == 0
    animator.set_surface_visible(False)


def test_interaction_menu_disables_gestures_missing_from_an_outfit(qtbot):
    bubble = PetBubble()
    qtbot.addWidget(bubble)
    bubble.set_interaction_capabilities(lambda action: action != 'yawn')
    assert not bubble._interaction_actions['item.stretch'].isEnabled()
    assert bubble._interaction_actions['item.play'].isEnabled()
