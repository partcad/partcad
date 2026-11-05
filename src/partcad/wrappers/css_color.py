#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A colour written in CSS, as the sRGB a display draws it in.

What a CMF declaration's 'display' is written in (see docs/design/cmf.md): any
notation CSS Color Level 4 has, so that a vendor states the look of its colour
however its own documents do - '#c91a09', 'rgb(201 26 9)', 'hsl(4 91% 41%)',
'oklch(52% 0.19 33)', 'firebrick'. Everything is read into one answer:
'(red, green, blue, alpha)', the channels integers from 0 to 255 in sRGB and
alpha a fraction from 0 to 1, which is what every drawing PartCAD makes is
drawn in and what 'to_hex' writes back as '#RRGGBB' or '#RRGGBBAA'.

A colour outside sRGB - a 'display-p3', 'lab' or 'oklch' one can be - is
clipped channel by channel rather than gamut-mapped as a browser would. A
display value is a hint for drawing a colour, not a statement of it (a CMF
declaration's claim is its name), and clipping is the simple, predictable
reading of a hint.

Plain Python on purpose: the core reads a declaration's display with it, and a
wrapper in a sandbox can import it too, as it imports 'kinematics'.
"""

import math
import re

# CSS's named colours: the 148 of CSS Color Level 4, as sRGB.
NAMED = {
    "aliceblue": "F0F8FF",
    "antiquewhite": "FAEBD7",
    "aqua": "00FFFF",
    "aquamarine": "7FFFD4",
    "azure": "F0FFFF",
    "beige": "F5F5DC",
    "bisque": "FFE4C4",
    "black": "000000",
    "blanchedalmond": "FFEBCD",
    "blue": "0000FF",
    "blueviolet": "8A2BE2",
    "brown": "A52A2A",
    "burlywood": "DEB887",
    "cadetblue": "5F9EA0",
    "chartreuse": "7FFF00",
    "chocolate": "D2691E",
    "coral": "FF7F50",
    "cornflowerblue": "6495ED",
    "cornsilk": "FFF8DC",
    "crimson": "DC143C",
    "cyan": "00FFFF",
    "darkblue": "00008B",
    "darkcyan": "008B8B",
    "darkgoldenrod": "B8860B",
    "darkgray": "A9A9A9",
    "darkgreen": "006400",
    "darkgrey": "A9A9A9",
    "darkkhaki": "BDB76B",
    "darkmagenta": "8B008B",
    "darkolivegreen": "556B2F",
    "darkorange": "FF8C00",
    "darkorchid": "9932CC",
    "darkred": "8B0000",
    "darksalmon": "E9967A",
    "darkseagreen": "8FBC8F",
    "darkslateblue": "483D8B",
    "darkslategray": "2F4F4F",
    "darkslategrey": "2F4F4F",
    "darkturquoise": "00CED1",
    "darkviolet": "9400D3",
    "deeppink": "FF1493",
    "deepskyblue": "00BFFF",
    "dimgray": "696969",
    "dimgrey": "696969",
    "dodgerblue": "1E90FF",
    "firebrick": "B22222",
    "floralwhite": "FFFAF0",
    "forestgreen": "228B22",
    "fuchsia": "FF00FF",
    "gainsboro": "DCDCDC",
    "ghostwhite": "F8F8FF",
    "gold": "FFD700",
    "goldenrod": "DAA520",
    "gray": "808080",
    "green": "008000",
    "greenyellow": "ADFF2F",
    "grey": "808080",
    "honeydew": "F0FFF0",
    "hotpink": "FF69B4",
    "indianred": "CD5C5C",
    "indigo": "4B0082",
    "ivory": "FFFFF0",
    "khaki": "F0E68C",
    "lavender": "E6E6FA",
    "lavenderblush": "FFF0F5",
    "lawngreen": "7CFC00",
    "lemonchiffon": "FFFACD",
    "lightblue": "ADD8E6",
    "lightcoral": "F08080",
    "lightcyan": "E0FFFF",
    "lightgoldenrodyellow": "FAFAD2",
    "lightgray": "D3D3D3",
    "lightgreen": "90EE90",
    "lightgrey": "D3D3D3",
    "lightpink": "FFB6C1",
    "lightsalmon": "FFA07A",
    "lightseagreen": "20B2AA",
    "lightskyblue": "87CEFA",
    "lightslategray": "778899",
    "lightslategrey": "778899",
    "lightsteelblue": "B0C4DE",
    "lightyellow": "FFFFE0",
    "lime": "00FF00",
    "limegreen": "32CD32",
    "linen": "FAF0E6",
    "magenta": "FF00FF",
    "maroon": "800000",
    "mediumaquamarine": "66CDAA",
    "mediumblue": "0000CD",
    "mediumorchid": "BA55D3",
    "mediumpurple": "9370DB",
    "mediumseagreen": "3CB371",
    "mediumslateblue": "7B68EE",
    "mediumspringgreen": "00FA9A",
    "mediumturquoise": "48D1CC",
    "mediumvioletred": "C71585",
    "midnightblue": "191970",
    "mintcream": "F5FFFA",
    "mistyrose": "FFE4E1",
    "moccasin": "FFE4B5",
    "navajowhite": "FFDEAD",
    "navy": "000080",
    "oldlace": "FDF5E6",
    "olive": "808000",
    "olivedrab": "6B8E23",
    "orange": "FFA500",
    "orangered": "FF4500",
    "orchid": "DA70D6",
    "palegoldenrod": "EEE8AA",
    "palegreen": "98FB98",
    "paleturquoise": "AFEEEE",
    "palevioletred": "DB7093",
    "papayawhip": "FFEFD5",
    "peachpuff": "FFDAB9",
    "peru": "CD853F",
    "pink": "FFC0CB",
    "plum": "DDA0DD",
    "powderblue": "B0E0E6",
    "purple": "800080",
    "rebeccapurple": "663399",
    "red": "FF0000",
    "rosybrown": "BC8F8F",
    "royalblue": "4169E1",
    "saddlebrown": "8B4513",
    "salmon": "FA8072",
    "sandybrown": "F4A460",
    "seagreen": "2E8B57",
    "seashell": "FFF5EE",
    "sienna": "A0522D",
    "silver": "C0C0C0",
    "skyblue": "87CEEB",
    "slateblue": "6A5ACD",
    "slategray": "708090",
    "slategrey": "708090",
    "snow": "FFFAFA",
    "springgreen": "00FF7F",
    "steelblue": "4682B4",
    "tan": "D2B48C",
    "teal": "008080",
    "thistle": "D8BFD8",
    "tomato": "FF6347",
    "turquoise": "40E0D0",
    "violet": "EE82EE",
    "wheat": "F5DEB3",
    "white": "FFFFFF",
    "whitesmoke": "F5F5F5",
    "yellow": "FFFF00",
    "yellowgreen": "9ACD32",
}

_NUMBER = r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
_TOKEN = re.compile(r"(%s)(%%|deg|grad|rad|turn)?|none" % _NUMBER)
_FUNCTION = re.compile(r"^([a-z-]+)\((.*)\)$")


def parse(text):
    """'text' as '(red, green, blue, alpha)', or None if it is no CSS colour."""
    if not isinstance(text, str):
        return None
    value = text.strip().lower()
    if not value:
        return None
    if value.startswith("#"):
        return _hex(value[1:])
    if value == "transparent":
        return (0, 0, 0, 0.0)
    if value in NAMED:
        return _hex(NAMED[value].lower())
    match = _FUNCTION.match(value)
    if match is None:
        return None
    function, arguments = match.groups()
    parsed = _arguments(arguments)
    if parsed is None:
        return None
    channels, alpha = parsed
    reader = _READERS.get(function)
    if reader is None:
        return None
    try:
        rgb = reader(channels)
    except (ValueError, IndexError, ZeroDivisionError):
        return None
    if rgb is None:
        return None
    return tuple(_byte(c) for c in rgb) + (_clamp(alpha),)


def to_hex(rgba):
    """'(red, green, blue, alpha)' as '#RRGGBB', with 'AA' only when it is not opaque."""
    red, green, blue, alpha = rgba
    text = "#%02X%02X%02X" % (red, green, blue)
    if alpha < 1.0:
        text += "%02X" % round(alpha * 255)
    return text


def normalize(text):
    """'text' read and written back the one way PartCAD writes a colour, or None."""
    rgba = parse(text)
    return None if rgba is None else to_hex(rgba)


def _hex(digits):
    if len(digits) not in (3, 4, 6, 8) or any(c not in "0123456789abcdef" for c in digits):
        return None
    if len(digits) in (3, 4):
        digits = "".join(c * 2 for c in digits)
    channels = [int(digits[i : i + 2], 16) for i in range(0, len(digits), 2)]
    alpha = channels[3] / 255.0 if len(channels) == 4 else 1.0
    return channels[0], channels[1], channels[2], alpha


def _arguments(text):
    """The channel tokens and the alpha of a function's arguments, in either syntax.

    The legacy one separates with commas and puts alpha fourth; the modern one
    separates with spaces and puts alpha after a '/'. A channel is kept as its
    '(number, unit)' and read by the function it belongs to, since what 100%
    means is the function's to say.
    """
    alpha = 1.0
    if "/" in text:
        text, _, alpha_text = text.partition("/")
        alpha = _alpha(alpha_text.strip())
        if alpha is None:
            return None
    parts = [p for p in re.split(r"[\s,]+", text.strip()) if p]
    if "," in text and len(parts) == 4:
        alpha = _alpha(parts.pop())
        if alpha is None:
            return None
    channels = []
    for part in parts:
        match = _TOKEN.fullmatch(part)
        if match is None:
            if re.fullmatch(r"[a-z][a-z0-9-]*", part):
                channels.append((part, None))
                continue
            return None
        if part == "none":
            channels.append((0.0, None))
        else:
            channels.append((float(match.group(1)), match.group(2)))
    return channels, alpha


def _alpha(text):
    match = _TOKEN.fullmatch(text)
    if match is None or text == "none":
        return None
    value = float(match.group(1))
    return value / 100.0 if match.group(2) == "%" else value


def _channel(token, percent_of):
    number, unit = token
    if isinstance(number, str):
        raise ValueError(number)
    return number * percent_of / 100.0 if unit == "%" else number


def _hue(token):
    number, unit = token
    if isinstance(number, str):
        raise ValueError(number)
    if unit in (None, "deg"):
        return number
    if unit == "rad":
        return math.degrees(number)
    if unit == "grad":
        return number * 0.9
    if unit == "turn":
        return number * 360.0
    raise ValueError(unit)


def _rgb(channels):
    if len(channels) != 3:
        return None
    return [_channel(c, 255.0) / 255.0 for c in channels]


def _hsl_to_rgb(hue, saturation, lightness):
    def f(n):
        k = (n + hue / 30.0) % 12
        a = saturation * min(lightness, 1 - lightness)
        return lightness - a * max(-1.0, min(k - 3, 9 - k, 1.0))

    return [f(0), f(8), f(4)]


def _hsl(channels):
    if len(channels) != 3:
        return None
    hue = _hue(channels[0])
    saturation = _channel(channels[1], 100.0) / 100.0
    lightness = _channel(channels[2], 100.0) / 100.0
    return _hsl_to_rgb(hue, _clamp(saturation), _clamp(lightness))


def _hwb(channels):
    if len(channels) != 3:
        return None
    hue = _hue(channels[0])
    white = _clamp(_channel(channels[1], 100.0) / 100.0)
    black = _clamp(_channel(channels[2], 100.0) / 100.0)
    if white + black >= 1:
        grey = white / (white + black)
        return [grey, grey, grey]
    return [c * (1 - white - black) + white for c in _hsl_to_rgb(hue, 1.0, 0.5)]


def _encode(linear):
    """Linear sRGB as the gamma-encoded sRGB a display is driven with."""
    sign = -1.0 if linear < 0 else 1.0
    linear = abs(linear)
    if linear <= 0.0031308:
        return sign * 12.92 * linear
    return sign * (1.055 * math.pow(linear, 1 / 2.4) - 0.055)


def _decode(encoded):
    sign = -1.0 if encoded < 0 else 1.0
    encoded = abs(encoded)
    if encoded <= 0.04045:
        return sign * encoded / 12.92
    return sign * math.pow((encoded + 0.055) / 1.055, 2.4)


def _multiply(matrix, vector):
    return [sum(m * v for m, v in zip(row, vector)) for row in matrix]


# The matrices of CSS Color Level 4's sample code.
_XYZ_D65_TO_LINEAR_SRGB = (
    (3.2409699419045226, -1.537383177570094, -0.4986107602930034),
    (-0.9692436362808796, 1.8759675015077202, 0.04155505740717559),
    (0.05563007969699366, -0.20397695888897652, 1.0569715142428786),
)
_D50_TO_D65 = (
    (0.9554734527042182, -0.023098536874261423, 0.0632593086610217),
    (-0.028369706963208136, 1.0099954580058226, 0.021041398966943008),
    (0.012314001688319899, -0.020507696433477912, 1.3303659366080753),
)
_LINEAR_P3_TO_XYZ_D65 = (
    (0.4865709486482162, 0.26566769316909306, 0.1982172852343625),
    (0.2289745640697488, 0.6917385218365064, 0.079286914093745),
    (0.0, 0.04511338185890264, 1.043944368900976),
)
_D50_WHITE = (0.3457 / 0.3585, 1.0, (1.0 - 0.3457 - 0.3585) / 0.3585)


def _lab_to_rgb(lightness, a, b):
    kappa, epsilon = 24389 / 27, 216 / 24389
    fy = (lightness + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200
    x = fx**3 if fx**3 > epsilon else (116 * fx - 16) / kappa
    y = ((lightness + 16) / 116) ** 3 if lightness > kappa * epsilon else lightness / kappa
    z = fz**3 if fz**3 > epsilon else (116 * fz - 16) / kappa
    xyz_d50 = [x * _D50_WHITE[0], y * _D50_WHITE[1], z * _D50_WHITE[2]]
    linear = _multiply(_XYZ_D65_TO_LINEAR_SRGB, _multiply(_D50_TO_D65, xyz_d50))
    return [_encode(c) for c in linear]


def _lab(channels):
    if len(channels) != 3:
        return None
    return _lab_to_rgb(_channel(channels[0], 100.0), _channel(channels[1], 125.0), _channel(channels[2], 125.0))


def _lch(channels):
    if len(channels) != 3:
        return None
    lightness = _channel(channels[0], 100.0)
    chroma = _channel(channels[1], 150.0)
    hue = math.radians(_hue(channels[2]))
    return _lab_to_rgb(lightness, chroma * math.cos(hue), chroma * math.sin(hue))


def _oklab_to_rgb(lightness, a, b):
    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_**3, m_**3, s_**3
    linear = [
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    ]
    return [_encode(c) for c in linear]


def _oklab(channels):
    if len(channels) != 3:
        return None
    return _oklab_to_rgb(_channel(channels[0], 1.0), _channel(channels[1], 0.4), _channel(channels[2], 0.4))


def _oklch(channels):
    if len(channels) != 3:
        return None
    lightness = _channel(channels[0], 1.0)
    chroma = _channel(channels[1], 0.4)
    hue = math.radians(_hue(channels[2]))
    return _oklab_to_rgb(lightness, chroma * math.cos(hue), chroma * math.sin(hue))


def _color(channels):
    """'color(<space> c1 c2 c3)' for the spaces a display colour may be written in."""
    if len(channels) != 4 or not isinstance(channels[0][0], str):
        return None
    space = channels[0][0]
    values = [_channel(c, 1.0) for c in channels[1:]]
    if space == "srgb":
        return values
    if space == "srgb-linear":
        return [_encode(c) for c in values]
    if space == "display-p3":
        xyz = _multiply(_LINEAR_P3_TO_XYZ_D65, [_decode(c) for c in values])
        return [_encode(c) for c in _multiply(_XYZ_D65_TO_LINEAR_SRGB, xyz)]
    if space in ("xyz", "xyz-d65"):
        return [_encode(c) for c in _multiply(_XYZ_D65_TO_LINEAR_SRGB, values)]
    if space == "xyz-d50":
        return [_encode(c) for c in _multiply(_XYZ_D65_TO_LINEAR_SRGB, _multiply(_D50_TO_D65, values))]
    return None


_READERS = {
    "rgb": _rgb,
    "rgba": _rgb,
    "hsl": _hsl,
    "hsla": _hsl,
    "hwb": _hwb,
    "lab": _lab,
    "lch": _lch,
    "oklab": _oklab,
    "oklch": _oklch,
    "color": _color,
}


def _clamp(value):
    return max(0.0, min(1.0, value))


def _byte(value):
    return int(round(_clamp(value) * 255))
