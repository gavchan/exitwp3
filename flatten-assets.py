#!/usr/bin/env python3

import os
import re
import sys
import pathlib
import shutil

# Flatten assets folder
   # Set location of output files

current_dir = pathlib.Path().absolute()
print(f"Output dir   : {current_dir}")
base_dir = os.path.join(current_dir, 'build\\gatsby\\aidanchan.wordpress.com\\')
assets_dir = os.path.join(base_dir, 'assets\\')
flatten_dir = os.path.join(base_dir, 'flattened\\')
asset_files = os.listdir(assets_dir)
# print(asset_files)

# Create new directory for flattened files if not exist
if (not os.path.exists(flatten_dir)):
    os.makedirs(flatten_dir)

for dirpath, dirnames, files in os.walk(assets_dir, topdown=True):
    for filename in files:
        src_filepath = pathlib.Path(os.path.join(dirpath, filename))
        dir_prefix = src_filepath.parent.name
        dest_filename = str(dir_prefix) + '_' + filename
        dest_filepath = os.path.join(flatten_dir, dest_filename)
        print('Copy ' + str(src_filepath) + ' => ' + str(dest_filepath))
        shutil.copy(src_filepath, dest_filepath)
