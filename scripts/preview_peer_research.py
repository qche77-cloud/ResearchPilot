"""Temporary fictional UI fixture. Real PDF parser is tested separately on filings."""
import runpy
from pathlib import Path
from unittest.mock import patch
import streamlit as st
from scripts.preview_cockpit import cockpit_service

FIXTURE_BYTES=b'%PDF-fictional-browser-fixture'


def fixture_extract(content):
    if content!=FIXTURE_BYTES:
        raise ValueError('此隔离预览仅接受浏览器验收夹具；真实 PDF 请在正式工作区导入')
    return [dict(page=1,text='离线虚构财报 公司代码 002837\n主要会计数据 2025年 2024年\n单位：元 币种：人民币\n营业收入 12000000.00 10000000.00\n归属于上市公司股东的净利润 800000.00 1000000.00')]


if __name__=='__main__':
    service=cockpit_service('peer-'+st.query_params.get('acceptance_token','default'))
    service._pdf_parser_fixture=fixture_extract
    with patch('src.financial_import.extract_pdf',side_effect=fixture_extract),patch('src.workbench_ui.fetch_stock',side_effect=RuntimeError('禁止外部 API')),patch('src.workbench_ui.fetch_directory',side_effect=RuntimeError('禁止外部 API')):
        runpy.run_path(str(Path(__file__).resolve().parents[1]/'studio_app.py'),run_name='__main__',init_globals={'_preview_service':service})
