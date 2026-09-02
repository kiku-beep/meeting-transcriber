import numpy as np

from backend.core.loopback_selector import LoopbackSourceSelector


SIGNAL = np.full(1600, 0.1, dtype=np.float32)
SILENCE = np.zeros(1600, dtype=np.float32)


def test_first_source_becomes_selected():
    selector = LoopbackSourceSelector()

    assert selector.should_emit(25, SIGNAL, now=0.0)
    assert selector.selected_source == 25


def test_selected_source_keeps_emitting_silent_frames():
    selector = LoopbackSourceSelector()
    selector.should_emit(25, SIGNAL, now=0.0)

    assert selector.should_emit(25, SILENCE, now=0.1)


def test_active_source_switches_after_selected_source_is_silent():
    selector = LoopbackSourceSelector(
        activity_threshold=0.001,
        switch_after_s=0.2,
    )
    selector.should_emit(25, SIGNAL, now=0.0)
    selector.should_emit(25, SILENCE, now=0.1)

    assert selector.should_emit(29, SIGNAL, now=0.21)
    assert selector.selected_source == 29


def test_other_source_does_not_take_over_while_selected_source_is_active():
    selector = LoopbackSourceSelector(
        activity_threshold=0.001,
        switch_after_s=0.2,
    )
    selector.should_emit(25, SIGNAL, now=0.0)
    selector.should_emit(25, SIGNAL, now=0.2)

    assert not selector.should_emit(29, SIGNAL, now=0.21)
    assert selector.selected_source == 25


def test_active_source_can_replace_initially_silent_source_immediately():
    selector = LoopbackSourceSelector()
    selector.should_emit(25, SILENCE, now=0.0)

    assert selector.should_emit(29, SIGNAL, now=0.01)
    assert selector.selected_source == 29


def test_remove_source_clears_selected_source():
    selector = LoopbackSourceSelector()
    selector.should_emit(25, SIGNAL, now=0.0)

    selector.remove_source(25)

    assert selector.selected_source is None
    assert selector.should_emit(29, SIGNAL, now=0.1)


def test_reset_clears_all_source_state():
    selector = LoopbackSourceSelector()
    selector.should_emit(25, SIGNAL, now=0.0)

    selector.reset()

    assert selector.selected_source is None
    assert selector.should_emit(29, SILENCE, now=0.1)
