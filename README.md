This package provides a CLI program that can fetch an HTML page and its dependencies
and inline most dependencies, producing a single file that can be loaded offline.

The things that are currently inlined are:
* CSS files
* JavaScript files
* CSS imports
* CSS fonts
* Images

SVG images are inlined directly as SVGs, while all other images (and font faces)
are converted to `data:` URLs.
