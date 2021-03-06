#!/usr/bin/env python3

import codecs
import os
import re
import sys
from datetime import datetime, timedelta, tzinfo
from glob import glob

from urllib.request import urlretrieve
from urllib.parse import urljoin, urlparse
from io import StringIO
import xml.etree.ElementTree as etree 

import yaml
from bs4 import BeautifulSoup

# Suppress "...looks like a URL... " warnings from BeautifulSoup
import warnings
warnings.filterwarnings("ignore", message='.*looks like a URL.*', category=UserWarning, module='bs4')

from html2text import html2text_file

'''
exitwp3 - Wordpress xml exports to Gatsby blog format conversion

Modification of exitwp.py by Thomas Frössman to use with Python 3
https://github.com/some-programs/exitwp

'''
######################################################
# Configration
######################################################
# config = yaml.load(file('config.yaml', 'r'))

with open('config.yaml') as f:
    config = yaml.load(f, Loader=yaml.FullLoader)
wp_exports = config['wp_exports']
build_dir = config['build_dir']
download_images = config['download_images']
use_hierarchical_folders = config['use_hierarchical_folders']
replace_existing = config['replace_existing']
target_format = config['target_format']
taxonomy_filter = set(config['taxonomies']['filter'])
taxonomy_entry_filter = config['taxonomies']['entry_filter']
taxonomy_name_mapping = config['taxonomies']['name_mapping']
item_type_filter = set(config['item_type_filter'])
item_field_filter = config['item_field_filter']
date_fmt = config['date_format']
body_replace = config['body_replace']


# Time definitions
ZERO = timedelta(0)
HOUR = timedelta(hours=1)


# UTC support
class UTC(tzinfo):
    """UTC."""

    def utcoffset(self, dt):
        return ZERO

    def tzname(self, dt):
        return 'UTC'

    def dst(self, dt):
        return ZERO


def html2fmt(html, target_format):
    #   html = html.replace("\n\n", '<br/><br/>')
    #   html = html.replace('<pre lang="xml">', '<pre lang="xml"><![CDATA[')
    #   html = html.replace('</pre>', ']]></pre>')
    if target_format == 'html':
        return html
    else:
        return html2text_file(html, None)


def parse_wp_xml(file):

    print(f'Parsing {file}')
    tree = etree.parse(file)
    root = tree.getroot()

    # Parse namespace prefixes from file
    ns_prefixes = dict([
        node for _, node in etree.iterparse(
            file, events=['start-ns'])
    ])
    # Specify empty namespace
    ns_prefixes[''] = ''

    # Append parentheses around prefixes for namespaces
    ns = {}
    for k,v in ns_prefixes.items():
        ns[k] = '{' + v + '}'

    c = root.find('channel')

    def parse_header():
        try:
            desc = str(c.find('description').text)
        except:
            desc = ''

        return {
            'title': str(c.find('title').text),
            'link': str(c.find('link').text),
            'description': desc,
        }

    def parse_items():
        export_items = []
        xml_items = c.findall('item')
        for i in xml_items:
            # Parse taxanomies
            taxanomies = i.findall('category')
            export_taxanomies = {}
            for tax in taxanomies:
                if 'domain' not in tax.attrib:
                    continue
                t_domain = str(tax.attrib['domain'])
                t_entry = str(tax.text)
                
                if (not (t_domain in taxonomy_filter) and
                    not (t_domain
                         in taxonomy_entry_filter and
                         taxonomy_entry_filter[t_domain] == t_entry)):
                    if t_domain not in export_taxanomies:
                        export_taxanomies[t_domain] = []
                    export_taxanomies[t_domain].append(t_entry)

            def gi(q, unicode_wrap=True, empty=False):
                namespace = ''
                tag = ''
                if q.find(':') > 0:
                    namespace, tag = q.split(':', 1)
                else:
                    tag = q
                try:
                    result = (i.find(q, ns) or i.find(tag) or i.find(ns[namespace] + tag)).text.strip()
                except AttributeError:
                    result = ''
                    # if empty:
                    #     result = ''
                if unicode_wrap:
                    result = str(result)
                return result

            body = gi('content:encoded')
            for key in body_replace:
                # body = body.replace(key, body_replace[key])
                body = re.sub(key, body_replace[key], body)

            img_srcs = []
            if body is not None:
                try:
                    soup = BeautifulSoup(body, 'html.parser')
                    img_tags = soup.find_all('img')
                    for img in img_tags:
                        img_srcs.append(img['src'])
                except:
                    print('could not parse html: ' + body)

            excerpt = gi('excerpt:encoded', empty=True)

            export_item = {
                'title': gi('title'),
                'link': gi('link'),
                'author': gi('dc:creator'),
                'date': gi('wp:post_date_gmt'),
                'description': gi('description'),
                'slug': gi('wp:post_name'),
                'status': gi('wp:status'),
                'type': gi('wp:post_type'),
                'wp_id': gi('wp:post_id'),
                'parent': gi('wp:post_parent'),
                'comments': gi('wp:comment_status') == 'open',
                'taxanomies': export_taxanomies,
                'body': body,
                'excerpt': excerpt,
                'img_srcs': img_srcs
            }

            export_items.append(export_item)

        return export_items

    return {
        'header': parse_header(),
        'items': parse_items(),
    }

def write_gatsby(data, target_format):
    """
    Write data to gatsby in target_format (.md, .markdown, .html)
    """
    print(f'Output format: .{target_format}')
    item_uids = {}
    attachments = {}

    def get_blog_path(data, path_infix='gatsby'):
        name = data['header']['link']
        name = re.sub('^https?', '', name)
        name = re.sub('[^A-Za-z0-9_.-]', '', name)
        return os.path.normpath(build_dir + '/' + path_infix + '/' + name)

    # Set location of output files
    blog_dir = get_blog_path(data)
    print(f"Output dir   : {blog_dir}")

    def get_full_dir(dir):
        full_dir = os.path.normpath(blog_dir + '/' + dir)
        if (not os.path.exists(full_dir)):
            os.makedirs(full_dir)
        return full_dir

    def open_file(file):
        f = codecs.open(file, 'w', encoding='utf-8')
        return f

    def get_item_uid(item, date_prefix=False, namespace=''):
        result = None
        if namespace not in item_uids:
            item_uids[namespace] = {}

        if item['wp_id'] in item_uids[namespace]:
            result = item_uids[namespace][item['wp_id']]
        else:
            uid = []
            if (date_prefix):
                try:
                    dt = datetime.strptime(item['date'], date_fmt)
                except:
                    dt = datetime.today()
                    print('Wrong date in', item['title'])
                uid.append(dt.strftime('%Y-%m-%d'))
                uid.append('-')
            s_title = item['slug']
            if s_title is None or s_title == '':
                s_title = item['title']
            if s_title is None or s_title == '':
                s_title = 'untitled'
            s_title = s_title.replace(' ', '_')
            s_title = re.sub('[^a-zA-Z0-9_-]', '', s_title)
            uid.append(s_title)
            fn = ''.join(uid)
            n = 1
            while fn in item_uids[namespace]:
                n = n + 1
                fn = ''.join(uid) + '_' + str(n)
                item_uids[namespace][i['wp_id']] = fn
            result = fn
        return result

    def get_item_path(item, dir=''):
        full_dir = get_full_dir(dir)
        filename_parts = [full_dir, '/']
        filename_parts.append(item['uid'])
        if item['type'] == 'page':
            if (not os.path.exists(''.join(filename_parts))):
                os.makedirs(''.join(filename_parts))
            filename_parts.append('/index')
        filename_parts.append('.')
        filename_parts.append(target_format)
        return ''.join(filename_parts)

    def get_attachment_path(src, dir, dir_prefix='assets'):
        try:
            files = attachments[dir]
        except KeyError:
            attachments[dir] = files = {}

        try:
            filename = files[src]
        except KeyError:
            file_root, file_ext = os.path.splitext(os.path.basename(
                urlparse(src)[2]))
            file_infix = 1
            if file_root == '':
                file_root = '1'
            current_files = list(files.values())
            maybe_filename = file_root + file_ext
            while maybe_filename in current_files:
                maybe_filename = file_root + '-' + str(file_infix) + file_ext
                file_infix = file_infix + 1
            files[src] = filename = maybe_filename

        if use_hierarchical_folders:
            target_dir = os.path.normpath(blog_dir + '/' + dir_prefix + '/' + dir)
            target_file = os.path.normpath(target_dir + '/' + filename)
        else:
            # Instead of hierarchical structure, use flat structure to save
            target_dir = os.path.normpath(blog_dir + '/' + dir_prefix)
            target_file = os.path.normpath(target_dir + '/' + dir + '_' + filename)

        if (not os.path.exists(target_dir)):
            os.makedirs(target_dir)

        # if src not in attachments[dir]:
        #     print target_name
        return target_file

    sys.stdout.write('Writing')
    for i in data['items']:
        skip_item = False

        for field, value in item_field_filter.items():
            if(i[field] == value):
                skip_item = True
                break

        if(skip_item):
            continue

        sys.stdout.write('.')
        sys.stdout.flush()
        out = None
        try:
            date = datetime.strptime(i['date'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC())
        except:
            date = datetime.today()
            print('Wrong date in', i['title'])
        yaml_header = {
            'title': i['title'],
            #'link': i['link'],
            #'author': i['author'],
            'date': date,
            'description': i['description'],
            'slug': '/'+i['slug'],
            #'wordpress_id': int(i['wp_id']),
            #'comments': i['comments'],
        }
        if len(i['excerpt']) > 0:
            yaml_header['excerpt'] = i['excerpt']
        if i['status'] != 'publish':
            yaml_header['published'] = False

        if i['type'] == 'post':
            i['uid'] = get_item_uid(i, date_prefix=True)
            fn = get_item_path(i, dir='_posts')
            out = open_file(fn)
            yaml_header['template'] = 'blog-post'
        elif i['type'] == 'page':
            i['uid'] = get_item_uid(i)
            # Chase down parent path, if any
            parentpath = ''
            item = i
            while item['parent'] != '0':
                item = next((parent for parent in data['items']
                             if parent['wp_id'] == item['parent']), None)
                if item:
                    parentpath = get_item_uid(item) + '/' + parentpath
                else:
                    break
            fn = get_item_path(i, parentpath)
            out = open_file(fn)
            yaml_header['template'] = 'page'
        elif i['type'] in item_type_filter:
            pass
        else:
            print('Unknown item type :: ' + i['type'])
            
        # Set featured image if images exists
        if i['img_srcs']:
            featured_image_path =  urljoin(data['header']['link'], str(i['img_srcs'][0]))
        else:
            featured_image_path = ''
        if download_images:
            counter = 0
            for img in i['img_srcs']:
                fullurl = urljoin(data['header']['link'], str(img))
                outpath = get_attachment_path(img, i['uid'])
                relpath = outpath.replace(blog_dir,'').replace('\\','/')

                if 'flickr.com' in fullurl:
                    # Convert Flickr "farm?.static..." url to downloadable url
                    downurl = re.sub('(farm\d.static.)', 'live.static', fullurl)
                    # Specify large size (1064)
                    downurl = re.sub('(.jpg)', '_b.jpg', downurl)
                else:
                    downurl = fullurl
                
                try_download = True
                if os.path.isfile(outpath):
                    if replace_existing: 
                        sys.stdout.write(f"Replacing image: {downurl} => {outpath}")
                        sys.stdout.flush()
                    else:
                        sys.stdout.write(f"Skip existing: {outpath}\n")
                        sys.stdout.flush()
                        i['body'] = i['body'].replace(fullurl, relpath)
                        try_download = False
                if try_download:
                    try:
                        sys.stdout.write(f"Downloading image")
                        urlretrieve(downurl, outpath)
                    except:
                        print('\nUnable to download ' + downurl)
                        print('Error: ', sys.exc_info()[0])
                        raise
                    else:
                        sys.stdout.write("...replace link...")
                        sys.stdout.flush()
                        try:
                            i['body'] = i['body'].replace(fullurl, relpath)
                        except Exception as e:
                            print(e)
                        else:
                            print("ok.")
                if counter == 0:
                    featured_image_path = relpath
                counter += 1
        yaml_header['featuredImage'] = featured_image_path

        if out is not None:
            def toyaml(data):
                return yaml.safe_dump(data, allow_unicode=True,
                                      default_flow_style=False)

            tax_out = {}
            for taxonomy in i['taxanomies']:
                for tvalue in i['taxanomies'][taxonomy]:
                    t_name = taxonomy_name_mapping.get(taxonomy, taxonomy)
                    if t_name not in tax_out:
                        tax_out[t_name] = []
                    if tvalue in tax_out[t_name]:
                        continue
                    tax_out[t_name].append(tvalue)

            out.write('---\n')
            if len(yaml_header) > 0:
                out.write(toyaml(yaml_header))
            if len(tax_out) > 0:
                out.write(toyaml(tax_out))

            out.write('---\n\n')
            try:
                out.write(html2fmt(i['body'], target_format))
            except:
                print('\n Parse error on: ' + i['title'])

            out.close()
    print('done\n')

wp_exports = glob(wp_exports + '/*.xml')
for wpe in wp_exports:
    data = parse_wp_xml(wpe)
    write_gatsby(data, target_format)
