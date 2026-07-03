# -*- coding: utf-8 -*-
"""
Created on 2026-07-03T15:45:03-04:00

@author: nate
"""
import argh
from loguru import logger

import nate_ntm


def main():
    logger.info(__name__)

def cli():
    parser = argh.ArghParser()
    parser.add_commands([
            main
    ])
    parser.dispatch()

    # Only one entrypoint
    #argh.dispatch_command(main)