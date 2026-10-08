"""Compatibility launcher for the editable SVG icon build."""

try:
    from scripts.build_brand_icons import draw_eye_icon, main
except ModuleNotFoundError:
    from build_brand_icons import draw_eye_icon, main

__all__ = ['draw_eye_icon', 'main']

if __name__ == '__main__':
    main()
