"""Implementation of the web page inliner."""

import base64
import logging

from urllib.parse import urlparse
from urllib.request import urlopen
from pathlib import Path

import click
import tinycss2
from bs4 import BeautifulSoup, Comment

log = logging.getLogger('inliner')
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
log.addHandler(handler)
log.setLevel(logging.INFO)

class InliningParser():
    """
    Main class that does all the work.

    Args:
    * `source` - URL or path to source file
    * `outf` - something that supports `.write(str)` for the result to be written to
    * `pretty` - if true, pretty-print the output HTML

    Note that `pretty` is a relative term here - no attempt is made to prettify
    eg inline JavaScript.
    """
    def __init__(self, source, outf, pretty, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            url = urlparse(source)
            self.base = f"{url.scheme}://{url.netloc}"
        except:
            source_path = Path(source).absolute()
            self.base = f"file://{source_path.parent}"
            source = source_path.name

        self.source = source
        self.outf = outf
        self.pretty = pretty

    def retrieve_file(self, name):
        """Get a file, possibly taking into account the root of the site, if the
        page was retrieved from a server.

        `name` can be a URL, an absolute path or a relative path."""
        try:
            url = urlparse(name)
            if not url.scheme:
                raise ValueError
            url = name

        except:
            if name.startswith('/'):
                url = self.base + name
            else:
                url = self.base + "/" + name

        response = urlopen(url)

        return response.info().get_content_type(), response.read()

    def load_css(self, href):
        """Retrive a CSS file and inline the things it imports."""
        log.info('Inlining CSS %s', href)
        content_type, content = self.retrieve_file(href)
        return self.inline_css_imports(content.decode('utf-8'), href)

    def inline_css_imports(self, content, href):
        """Inline imports and fonts into a CSS file."""
        stylesheet = tinycss2.parse_stylesheet(content)
        for rule in stylesheet:
            if rule.type == "error":
                log.error("Parse error in CSS at %s:%d:%d", href, rule.source_line, rule.source_column)
        ii = 0
        while ii < len(stylesheet):
            rule = stylesheet[ii]
            if (rule.type == 'comment'):
                stylesheet = stylesheet[:ii] + stylesheet[ii+1:]
                continue
            if (rule.type == "at-rule" and
                    rule.at_keyword == "import"
            ):
                f = rule.prelude[1]
                assert f.name == "url"
                args = f.arguments
                url = args[0]
                sub_stylesheet = self.load_css(url.value)
                stylesheet = stylesheet[:ii] + sub_stylesheet + stylesheet[ii+1:]
            if (rule.type == "at-rule" and
                rule.at_keyword == "font-face"):
                for token in rule.content:
                    if (token.type == "function" and
                        token.name == "url"):
                        url = token.arguments[0].value
                        if url.startswith('data:'):
                            log.info("Found already-inline CSS font")
                        else:
                            log.info("Inlining CSS font %s", url)
                            content_type, content = self.retrieve_file(url)
                            token.arguments[0].representation = self.data_as_url(content, content_type)

            ii += 1
        return stylesheet

    def data_as_url(self, content, content_type):
        """Convert byte data to a `data:` url of the given content type."""
        encoded = base64.standard_b64encode(content).decode('utf-8')
        return f"data:{content_type};base64,{encoded}"

    def process(self):
        """Actually do the inlining"""
        content_type, content = self.retrieve_file(self.source)
        soup = BeautifulSoup(content, "lxml")
        for tag in soup.find_all("noscript"):
            tag.decompose()

        for tag in soup.find_all(string=lambda text: isinstance(text, Comment)):
            tag.decompose()

        for tag in soup.find_all('style'):
            stylesheet = self.inline_css_imports(tag.string, 'inline')
            tag.string = ("\n" if self.pretty else "").join(rule.serialize() for rule in stylesheet)

        for tag in soup.find_all('link'):
            if 'stylesheet' in tag.get('rel'):
                href = None
                if tag.get('href'):
                    href = tag.get('href')
                    del tag['href']
                elif tag.get('data-href'):
                    href = tag.get('data-href')
                    del tag['data-href']
                if href:
                    stylesheet = self.load_css(href)
                    style = soup.new_tag('style')
                    style.string = "".join(rule.serialize() for rule in stylesheet)
                    tag.replace_with(style)

        for tag in soup.find_all('script'):
            if tag.get('src'):
                log.info('Inlining JavaScript %s', tag.get('src'))
                content_type, content = self.retrieve_file(tag.get('src'))
                del tag['src']
                tag.string = content.decode('utf-8')

        for tag in soup.find_all('img'):
            if tag.get('src').startswith('data:'):
                log.info("Found already-inline image")
            else:
                content_type, content = self.retrieve_file(tag.get('src'))
                log.info("Inlining %s image from %s", content_type, tag.get('src'))
                if content_type == 'image/svg+xml':
                    image_soup = BeautifulSoup(content, 'lxml')
                    tag.replace_with(image_soup)
                else:
                    tag['src'] = self.data_as_url(content, content_type)

        for tag in soup.find_all('svg'):
            log.info("Found SVG already inline")

        if self.pretty:
            self.outf.write(str(soup.prettify()))
        else:
            self.outf.write(str(soup))

@click.command()
@click.option('--output', '-o', default="index.html")
@click.option('--pretty/--no-pretty', default=False)
@click.argument('name')
def main(output, name, pretty):
    """Main CLI"""
    out = Path(output).open('w')
    InliningParser(name, out, pretty).process()

if __name__ == '__main__':
    main()