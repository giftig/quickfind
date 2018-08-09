#!/usr/bin/env python2.7
import argparse
import re
import subprocess

SEARCH_DEFS = 'defs'
SEARCH_FILES = 'files'
SEARCH_CLASSES = 'classes'
SEARCH_IMPORTS = 'imports'
SEARCH_USAGES = 'usages'

SEARCH_MODES = (
    SEARCH_DEFS, SEARCH_FILES, SEARCH_CLASSES, SEARCH_IMPORTS, SEARCH_USAGES
)

FORMAT_COORDS = 'coords'
FORMAT_FILES = 'file_list'
FORMAT_IMPORT = 'clean_imports'
FORMAT_QUICKFIX = 'quickfix'
FORMAT_RAW = 'raw'

FORMATS = (FORMAT_COORDS, FORMAT_FILES, FORMAT_QUICKFIX, FORMAT_RAW)


class Hit(object):
    def __init__(self, term, fn, text, line=None, col=None):
        self.term = term
        self.filename = fn
        self.text = text
        self.line = line
        self.col = col


class QuickFind(object):
    def __init__(
        self,
        term,
        search_type=SEARCH_FILES,
        format=FORMAT_RAW,
        single_result=False
    ):
        self.term = term
        self.search_type = search_type
        self.format = format
        self.single_result = single_result

    def _call_ag(self, args):
        """
        Call ag with the given arguments and fetch the raw output, split into
        lines. Handle errors in the subprocess, and squash the case where there
        are no results (i.e. exit code non-zero and no output)
        """
        cmd = ['ag'] + args

        output = None
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            if e.output:
                raise

            output = ''

        results = [
            l.strip() for l in output.split('\n')
        ]
        return [r for r in results if r]

    def _search_files(self):
        """
        Just return hits containing filename results. Search with ag -g
        """
        results = self._call_ag(['-g', self.term])
        return [Hit(self.term, r, None) for r in results]

    def _search_content(self, regex):
        """
        Do a full search of files and collect all the relevant data into Hits
        """
        results = self._call_ag(['-s', '--column', regex])
        parsed = []

        for r in results:
            r = r.strip()
            if not r:
                continue

            pieces = r.split(':')
            parsed.append(Hit(
                self.term,
                pieces[0],
                ':'.join(pieces[3:]),
                pieces[1],
                pieces[2],
            ))
        return parsed

    def search(self):
        if self.search_type == SEARCH_FILES:
            return self._search_files()

        raw_term = r'\Q%s\E' % self.term
        regex = {
            SEARCH_DEFS: r'def %s[\[\(: ]',
            SEARCH_CLASSES: (
                r'(?:class|trait|object|type)%s(?:[\[\(\{ ]|$)',
            ),
            SEARCH_IMPORTS: r'import .*[\.\{, ]%s',
            SEARCH_USAGES: r'%s'
        }.get(self.search_type, r'%s') % raw_term

        return self._search_content(regex)

    def _generate_import(self, hit):
        """Generate a scala import based on the search term and hit"""
        prefix = re.sub(r'^\s*import ([^\s]+\.).*$', r'\1', hit)
        return 'import %s.%s' % (prefix, self.term)

    def format_hit(self, hit):
        if self.format == FORMAT_FILES:
            return hit.filename

        if self.format == FORMAT_QUICKFIX:
            return '%s:%s:%s:%s' % (hit.filename, hit.line, hit.col, hit.text)

        if self.format == FORMAT_COORDS:
            return '%s:%s:%s' % (hit.filename, hit.line, hit.col)

        if self.format == FORMAT_IMPORT:
            return self._generate_import(hit.text)

        raise Exception('Unsupported format %s' % self.format)

    def run(self):
        hits = self.search()
        formatted = [self.format_hit(h) for h in hits]
        unique = set(formatted)
        results = sorted(list(unique))

        if self.single_result and self.results:
            results = results[0]

        for h in results:
            print(h)


def main():
    parser = argparse.ArgumentParser('quickfind v2')
    parser.add_argument(
        '-d', '--def', '--definition', dest=SEARCH_DEFS, action='store_true',
        help='Search for defs / methods / functions'
    )
    parser.add_argument(
        '-c', '--class', '--trait', dest=SEARCH_CLASSES, action='store_true',
        help='Search for classes / traits'
    )
    parser.add_argument(
        '-i', '--import', dest=SEARCH_IMPORTS, action='store_true',
        help='Search for imports'
    )
    parser.add_argument(
        '-f', '--file', dest=SEARCH_FILES, action='store_true',
        help='Search for filenames'
    )
    parser.add_argument(
        '-u', '--usage', dest=SEARCH_USAGES, action='store_true',
        help='Search for usages (i.e. any appearance of the term)'
    )
    parser.add_argument(
        '-l', '--list', dest=FORMAT_FILES, action='store_true',
        help='List resulting filenames only'
    )
    parser.add_argument(
        '-1', dest='single_result', action='store_true',
        help='Provide only the first hit'
    )
    parser.add_argument(
        '-x', '--coords', dest=FORMAT_COORDS, action='store_true',
        help='Provide line/col coordinates to the resulting hit'
    )
    parser.add_argument(
        '--clean-import', dest='clean_import', action='store_true',
        help=(
            'Only valid with -i. Provide import hits reformatted to remove '
            'other imports in the block found, providing an import statement '
            'which only imports the specified type'
        )
    )
    parser.add_argument(
        '-q', '--quickfix', dest=FORMAT_QUICKFIX, action='store_true',
        help='Provide hits in vim\'s quickfix format, with lines and cols'
    )
    parser.add_argument('term', type=str)
    args = parser.parse_args()

    search_mode = SEARCH_FILES
    found_mode = False
    for mode in SEARCH_MODES:
        if getattr(args, mode, None) is True:
            if found_mode:
                raise Exception('Multiple search types specified')

            search_mode = mode
            found_mode = True

    format = FORMAT_RAW
    found_format = False
    for f in FORMATS:
        if getattr(args, f, None) is True:
            if found_format:
                raise Exception('Multiple formats specified')

            format = f
            found_format = True

    if args.clean_import:
        if search_mode != SEARCH_IMPORTS:
            raise Exception('--clean-import can only be used with -i')

        format = FORMAT_IMPORT

    args.term = args.term.strip()
    if not args.term:
        raise Exception('Empty or whitespace-only search term provided')

    if search_mode == SEARCH_FILES:
        if format not in {FORMAT_RAW, FORMAT_FILES}:
            raise Exception('Bad format type while searching for files')

        format = FORMAT_FILES

    finder = QuickFind(
        term=args.term,
        search_type=search_mode,
        format=format,
        single_result=args.single_result
    )
    finder.run()


if __name__ == '__main__':
    main()
