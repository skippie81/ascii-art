#!/usr/bin/env python3
import binascii
import hashlib
import json
import logging
import os
import random
import re
import sys
import argparse
import base64
import tempfile
import textwrap
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

log = logging.getLogger('ASCII-ART Server')
log.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
ch.setFormatter(fmt)
log.addHandler(ch)

HTTP_PORT = 80
IP = ''

TEXT_WRAP_WITH = 80

B64_DATA_HEADER = '----------------------BEGIN OF ASCIIART OBJECT----------------------------------'
B64_DATA_FOOTER = '-----------------------END OF ASCIIART OBJECT-----------------------------------'
ART_SEPERATOR = '----------------------------ASCII ART ITEM--------------------------'

HTML_FORMAT = "<html>" \
              "<head></head>" \
              "<body style='color:#000;background-color:#FFF;'>" \
              "<div style='position:float;align:center;margin:auto;'>" \
              "<pre style='font-family:courier;font-size:12pt;'>{art}</pre></div>" \
              "<div style='margin-top:50px;margin-left:30px;'><a href='{id}' style='color:#AAA;'>{link}</a>" \
              "</body>" \
              "</html>"

class AsciiArt(object):
    def __init__(self, b:bytes=None):
        if b is not None:
            b64 = base64.b64encode(b)
            self._data = b64
            self._md5 = hashlib.sha1(self.data).hexdigest()

    def trim(self):
        my_str = self.__str__()

        def trimmer(text: str):
            empty_line = re.compile('^( *)$')
            head = True
            trimmed = []
            for line in text.split('\n'):
                if head:
                    if empty_line.match(line):
                        log.debug('empty line detected')
                        continue
                    head = False
                trimmed.append(line)
            return '\n'.join(trimmed)

        my_str = trimmer(my_str)
        my_str = trimmer('\n'.join(my_str.split('\n').__reversed__()))
        my_str = '\n'.join(my_str.split('\n').__reversed__())

        return AsciiArt(my_str.encode('utf-8'))

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value: bytes):
        if type(value) != bytes:
            value = value.encode('utf-8')
        self._data = value

    @property
    def md5(self):
        return self._md5

    @md5.setter
    def md5(self, value):
        self._md5 = value

    def __eq__(self, other):
        return self.md5 == other.md5

    def __str__(self):
        str = base64.b64decode(self.data).decode('utf-8')
        return str

    def __repr__(self):
        log.debug('Representing class %s' % self.md5)
        js = {'__class__': 'AsciiArt', 'data': self.data.decode('utf-8'), 'md5': self.md5}
        return js


class AsciiArtJsonEncoder(json.JSONEncoder):
    def default(self, o: AsciiArt):
        log.debug('Encoding %s as json' % o.md5)
        return o.__repr__()


class AsciiArtJsonDecoder(json.JSONDecoder):
    def __init__(self):
        log.debug('Loading AsciiArtJsonDecoder')
        json.JSONDecoder.__init__(self, object_hook=AsciiArtJsonDecoder.from_dict)

    @staticmethod
    def from_dict(d):
        log.debug('Decoding item')
        if d.get('__class__') == 'AsciiArt':
            log.debug('item is of AsciiArt sort')
            a = AsciiArt()
            a.data = d['data']
            a.md5 = d['md5']
            return a
        return d


class ArtDisplayer(BaseHTTPRequestHandler):
    ART_DB = None

    @classmethod
    def set_db(cls,db):
        cls.ART_DB = db

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()

    def do_GET(self):
        html = False
        rnd_item = random.randrange(0, self.ART_DB.len() - 1)
        log.debug('Request: %s' % self.request)
        log.debug('Headers: %s' % self.headers)
        log.debug('Path: %s' % self.path)

        if self.headers.get('accept') is not None:
            if 'text/html' in self.headers.get('accept').split(','):
                log.debug('html requested')
                html = True

        if self.path != '/':
            id = os.path.basename(self.path)
            log.debug('Basename: %s' % id)
            try:
                rnd_item = int(id)
                rnd_item = rnd_item % self.ART_DB.len()
            except ValueError:
                pass
            log.debug('Id: %s as %s' % (id, type(id)))

        log.info('Serving ASCII item #%s' % rnd_item)

        log.debug('Sending response')
        self.send_response(200)
        if html:
            self.send_header('Content-type', 'text/html; charset=utf-8')
        else:
            self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()

        log.debug('Reading art item #%s' % rnd_item)
        d = self.ART_DB.get(rnd_item)
        log.debug('Loaded %s' % type(d))

        d = str(d)
        if html:
            d = HTML_FORMAT.format(art=d, id=rnd_item, link='link')
        self.wfile.write(d.encode('utf-8'))
        return


class ArtDB(object):
    def __init__(self):
        self.ascii_arts = []
        self.b64 = False

    def open(self, args):
        with open(args.json[0], 'r') as jsonfile:
            log.info('Loading art objects from DB %s' % args.json[0])
            json_string = jsonfile.readlines()
            jsonfile.close()

            if json_string[0].rstrip() == B64_DATA_HEADER:
                log.debug('File contains Base64 AsciiArt object')
                json_string = [i.rstrip() for i in json_string[1:len(json_string)-1]]

            json_string = ''.join(json_string)

            try:
                json_string = base64.b64decode(json_string, validate=True)
                log.debug('Plain base64 data loaded')
                self.b64 = True
            except binascii.Error:
                pass

            self.ascii_arts = json.loads(json_string, cls=AsciiArtJsonDecoder)
            log.info('%s art objects loaded' % len(self.ascii_arts))
            jsonfile.close()

    def write_db(self, dbfile, b64=False, text_wrap=True):
        log.info('Writing DB file %s' % dbfile)
        log.debug('Encodig objects as JSON')
        json_string = json.dumps(self.ascii_arts, cls=AsciiArtJsonEncoder, indent=4)
        log.debug('JSON created')

        if b64 or self.b64:
            log.debug('Base64 encoding')
            json_string = base64.b64encode(json_string.encode('utf-8')).decode('utf-8')
            if  text_wrap:
                json_string = B64_DATA_HEADER + '\n'\
                              + '\n'.join(textwrap.wrap(json_string, width=TEXT_WRAP_WITH))\
                              + '\n' + B64_DATA_FOOTER

        log.debug('Writing file')
        with open(dbfile, 'w') as outfile:
            outfile.write(json_string)
            outfile.close()
        log.info('Written %s objecs in DB: %s' % (len(self.ascii_arts), dbfile))

    def add(self, art_object: AsciiArt):
        if art_object not in self.ascii_arts:
            self.ascii_arts.append(art_object)

    def len(self):
        return len(self.ascii_arts)

    def get(self,id : int):
        return self.ascii_arts[id]

    def remove(self, item: AsciiArt):
        self.ascii_arts.remove(item)

    def replace(self,index: int, new_item: AsciiArt):
        self.ascii_arts[index] = new_item

    def insert(self, index: int, art_object: AsciiArt):
        if art_object not in self.ascii_arts:
            self.ascii_arts.insert(index, art_object)

    def __str__(self):
        return json.dumps(self.ascii_arts, indent=4, cls=AsciiArtJsonEncoder)

    def __iter__(self):
        self.counter = -1
        return self

    def __next__(self):
        try:
            self.counter += 1
            return self.ascii_arts[self.counter]
        except IndexError:
            raise StopIteration


def parser(args):
    parser = argparse.ArgumentParser('ASCII-ART server')
    parser.add_argument('-v', '--verbose', help='verbose logging', action='store_true')

    cmd = parser.add_subparsers(dest='command', metavar='COMMAND')
    srv = cmd.add_parser('serve', help='Run HTTP server')
    srv.add_argument('-P', '--port', help='server port', default=HTTP_PORT, type=int)
    srv.add_argument('-l', '--listen-address', help='Listen on ip adress', default=IP)
    srv.add_argument('json', metavar='JSON_DATA', nargs=1, help='Server data file')

    load = cmd.add_parser('load', help='Load from txt files')
    load.add_argument('-o', '--out', help='Output DB file')
    load.add_argument('-a', '--append', help='Append to current DB file', action='store_true')
    load.add_argument('-t', '--trim', help='Remove empty lines on top/bottom of object', action='store_true')
    load.add_argument('--b64', help='Base64 encoded DB file', action='store_true')
    load.add_argument('--no-wrap', help='Base64 encoded DB file is not line wrapped', action='store_true')
    load.add_argument('files', help='Ascii art files', nargs='+', metavar='FILES')

    write = cmd.add_parser('write', help='Write json data to TXT files')
    write.add_argument('-p', '--prefix', help='File prefix', default='')
    write.add_argument('-s', '--suffix', help='File suffix', default='')
    write.add_argument('-e', '--extension', help='File extension', default='txt')
    write.add_argument('-o', '--one-file', help='Write all to one file', action='store_true')
    write.add_argument('--b64', help='Base64 encoded file(s)', action='store_true')
    write.add_argument('json', metavar='JSON_DATA', nargs=1, help='DB file')
    write.add_argument('dir', metavar='DIR|FILE', help='Directory to write all files', nargs=1)

    browse = cmd.add_parser('browse', help='Display and browse objecs')
    browse.add_argument('json', metavar='JSON_DATA', nargs=1, help='DB file')

    return parser.parse_args(args)


def serve(db: ArtDB, ip='', port=HTTP_PORT):
    try:
        ArtDisplayer.set_db(db)
        listener = (ip, port)
        log.info('serving on %s:%s' % listener)
        server = HTTPServer(listener, ArtDisplayer)
        server.serve_forever()
    except KeyboardInterrupt:
        log.warning('^C received, shutting down')
        server.socket.close()


def load_txt_file(filename):
    arts = []
    lines = ''

    with open(filename,'r') as fh:
        for line in fh.readlines():
            if ART_SEPERATOR not in line:
                lines += line
            else:
                if lines != '':
                    try:
                        lines = base64.b64decode(
                            lines.replace('\n', '').encode('utf-8'),
                            validate=True).decode('utf-8')
                    except binascii.Error:
                        pass
                    log.debug('One object read in file with more objects')
                    arts.append(lines.encode('utf-8'))
                    lines = ''
        fh.close()
        if lines != '':
            try:
                lines = base64.b64decode(
                    lines.replace('\n', '').encode('utf-8'),
                    validate=True).decode('utf-8')
            except binascii.Error as e:
                pass
            arts.append(lines.encode('utf-8'))
    return arts


def load_files(args, db: ArtDB):
    if args.append:
        if args.out is None:
            log.warning('Can not append, no output db file given')
        elif not os.path.isfile(args.out):
            log.warning('Can not append, DB file does not exist yet')
        else:
            args.json = [args.out]
            db.open(args)

    log.info('Loading %s files' % len(args.files))
    for file_name in args.files:
        arts = load_txt_file(file_name)
        for art in arts:
            art = AsciiArt(art)
            if args.trim:
                art = art.trim()
            db.add(art)
        log.info('%s unique art objects loaded' % db.len())

    if args.out is None:
        print('%s' % db)
    else:
        db.write_db(args.out, b64=args.b64, text_wrap=(not args.no_wrap))


def browser(args, db: ArtDB):
    log.info('Starting ASCII Art browser (%s objects)' % db.len())

    time.sleep(2)
    c = 1
    while c <= db.len():
        if not args.verbose:
            os.system('clear')
        log.debug('counter: %s' %  c)

        size = os.get_terminal_size()

        print('#'*size.columns)
        print(db.get(c-1))
        print('#'*size.columns)

        while True:
            go = input('ASCII object #%s/%s -- N(ext) p(revious) d(elete) e(dit) q(uit) : ' % (c, db.len()))
            if go.lower() in ['n', 'Next', '']:
                log.debug('next command')
                c += 1
            elif go.lower() in ['p', 'previous']:
                log.debug('previous command')
                c -= 1
            elif go.lower() in ['d','delete']:
                log.debug('delete command')
                log.info('Removing from DB')
                db.remove(db.get(c-1))
                time.sleep(1)
            elif go.lower() in ['e', 'edit']:
                log.debug('edit command')
                log.debug('creating tempfile')
                old = db.get(c-1)
                temp = tempfile.NamedTemporaryFile(delete=False)
                log.debug('writing object to tempfile %s' % temp.name)
                temp.write(str(old).encode('utf-8'))
                temp.close()
                log.debug('starting editor %s' % temp.name)
                os.system('vi %s' % temp.name)
                log.debug('reading edited file %s' % temp.name)

                arts = load_txt_file(temp.name)
                os.remove(temp.name)

                log.debug('removing original item #%s' % c)
                db.remove(old)

                for art in arts:
                    log.debug('inserting new item at #%s' % c)
                    art = AsciiArt(art)
                    db.insert(c-1, art)

            elif go.lower() in ['q', 'quit', 'exit']:
                log.debug('quit command')
                c = -1
            else:
                log.error('Wrong input: %s' % go)
                continue
            break

        if c > db.len():
            c = 1
        elif c == 0:
            c = db.len()
        elif c < 0:
            break

    if not args.verbose:
        os.system('clear')
    log.info('Done browsing, kept %s objects' % db.len())

    while True:
        save = input('Save updates to DB [y/n]: ')
        if save.lower() in ['y', 'yes']:
            db.write_db(args.json[0])
            break
        elif save.lower() in ['n','no']:
            break
        log.error('Incorrect input')


def write_files(args, db: ArtDB):
    if not args.one_file and not os.path.isdir(args.dir[0]):
        log.error('%s is not a directory' % args.dir[0])
        return 1

    write_mode = 'w'
    if args.one_file:
        write_mode = 'a'

    for art in db:
        file_name = args.dir[0]
        if not args.one_file:
            unique = uuid.uuid4()
            file_name = os.path.join(file_name, '%s%s%s.%s' % (args.prefix, unique, args.suffix, args.extension))

        log.debug('Writing object')
        with open(file_name, write_mode) as fh:
            if args.b64:
                art = '\n'.join(textwrap.wrap(
                    base64.b64encode(str(art).encode('utf-8')).decode('utf-8'),
                    width=TEXT_WRAP_WITH))

            fh.write('%s' % art)
            if args.one_file:
                fh.write('\n%s\n' % ART_SEPERATOR)
            fh.close()


def main(args):
    args = parser(args)

    if args.verbose:
        log.setLevel(logging.DEBUG)
        log.debug('Debug logging enabled')

    db = ArtDB()

    if args.command == 'load':
        load_files(args, db)
        return 0
    else:
        if not os.path.isfile(args.json[0]):
            log.error('%s does not exist' % args.json[0])
            return 1

        db.open(args)

        if args.command == 'serve':
            serve(db, ip=args.listen_address, port=args.port)
        elif args.command == 'write':
            write_files(args, db)
        elif args.command == 'browse':
            browser(args, db)

    return 0


if '__main__' in __name__:
    rc = main(sys.argv[1:])
    sys.exit(rc)