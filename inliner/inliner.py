import base64
import logging

from urllib.parse import urlparse
from urllib.request import urlopen
from html.parser import HTMLParser
from pathlib import Path

import click
import tinycss2

log = logging.getLogger('inliner')
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
log.addHandler(handler)
log.setLevel(logging.INFO)

class InliningParser(HTMLParser):
    def __init__(self, source, outf, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.source = source
        try:
            url = urlparse(source)
            self.base = f"{url.scheme}://{url.netloc}"
        except:
            source_path = Path(source).absolute()
            self.base = f"file://{source_path.parent}"
            source = source_path.name

        self.outf = outf
        self.skipping = []
        self.in_style = False
        self.feed(self.retrieve_file(source)[1].decode('utf-8'))

    def retrieve_file(self, name):
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
        log.info('Inlining CSS %s', href)
        content_type, content = self.retrieve_file(href)
        return self.inline_css_imports(content.decode('utf-8'), href)

    def inline_css_imports(self, content, href):
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
                        log.info("Inlining CSS font %s", url)
                        content_type, content = self.retrieve_file(url)
                        token.arguments[0].representation = f'"data:{content_type};{base64.standard_b64encode(content)}"'

            ii += 1
        return stylesheet

    def handle_starttag(self, tag, attrs):
        attr_dict = {x: y for x, y in attrs}
        if tag == "noscript":
            self.skipping.append(tag)
            return
        if self.skipping:
            return
        if tag == "svg":
            log.info("Found SVG already inline")
        if tag == "link":
            if attr_dict.get('rel') == "stylesheet":
                href = None
                if attr_dict.get('href'):
                    href = attr_dict.get('href')
                    del attr_dict['href']
                elif attr_dict.get('data-href'):
                    href = attr_dict.get('data-href')
                    del attr_dict['data-href']
                if href:
                    stylesheet = self.load_css(href)
                    self.outf.write("<style>")
                    for rule in stylesheet:
                        self.outf.write(rule.serialize())
                    self.outf.write(f"</style>")
                    return
        if tag == "style":
            self.outf.write(f'<{tag}>')
            self.in_style = True
            self.style_data = ""
            return
        if tag == "script":
            if attr_dict.get('src'):
                log.info('Inlining JavaScript %s', attr_dict.get('src'))
                content_type, content = self.retrieve_file(attr_dict.get('src'))
                self.outf.write(f"<script>{content.decode('utf-8')}")
                return

        if tag == "img":
            log.info("Found image at %s", attr_dict.get('src'))
        #     if attr_dict.get('src').startswith('data:'):
        #         pass
        #     else:
        #         url = attr_dict.get('src')
        #         content_type, content = self.retrieve_file(url)

        #         attr_dict['src'] = f"data:{content_type};{base64.standard_b64encode(content)}"

        self.outf.write("<{tag} {attrs}>".format(
            tag=tag,
            attrs=" ".join(f'{x}="{y}"' for x,y in attrs)
        ))

    def handle_endtag(self, tag):
        if self.skipping and tag == self.skipping[-1]:
            self.skipping.pop()
            return
        if self.in_style:
            self.in_style = False
            stylesheet = self.inline_css_imports(self.style_data, 'inline')
            for rule in stylesheet:
                self.outf.write(rule.serialize())
        self.outf.write(f"</{tag}>")

    def handle_data(self, data):
        if self.in_style:
            self.style_data += data
            return
        self.outf.write(data)

    def handle_comment(self, data):
        pass

    def handle_decl(self, data):
        self.outf.write(f"<!{data}>\n")

    def handle_pi(self, data):
        self.outf.write(f"<?{data}>")


@click.command()
@click.option('--output', '-o', default="index.html")
@click.argument('name')
def main(output, name):
    out = Path('index.html').open('w')
    InliningParser(name, out)

if __name__ == '__main__':
    main()