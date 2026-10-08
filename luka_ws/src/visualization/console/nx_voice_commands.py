"""Compatibility names; natural-language routing belongs to Moss."""


def hold_level(noise, peak):
    return max(0.0025, noise * 1.6, min(0.025, peak * 0.12))


def route(text):
    raise RuntimeError('Natural-language commands are handled by luka-ws-moss.service')


def destination_intent(text, destinations):
    raise RuntimeError('Use the dynamic destination capability through Moss')


def correct_room_command(text):
    return text
