"""Bounded literal spreadsheet projection from already verified attachment bytes.

No workbook engine, formula evaluation, macro execution, extraction to disk or
external relationship resolution. Unsupported/encrypted/oversize formats fail
closed to the existing verified download, never launch another application.
"""
from __future__ import annotations
import csv
import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

MAX_INPUT=5*1024*1024
MAX_EXPANDED=10*1024*1024
MAX_XML=2*1024*1024
MAX_ROWS=50
MAX_COLS=20
MAX_SHEETS=3
MAX_TEXT=500
S='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def _xml(data):
    if len(data)>MAX_XML:raise ValueError('Spreadsheet part exceeds preview limit')
    text=data.decode('utf-8-sig')
    if '\x00' in text or re.search(r'<!\s*(DOCTYPE|ENTITY)',text,re.I):raise ValueError('XML declarations are not supported for preview')
    return ET.fromstring(text)


def _literal(value):
    return str(value or '')[:MAX_TEXT]


def spreadsheet(data: bytes, mime: str, name: str) -> dict:
    if len(data)>MAX_INPUT:raise ValueError('Spreadsheet exceeds bounded preview size')
    suffix=name.rsplit('.',1)[-1].lower()
    if suffix in {'csv','tsv'} and mime.split(';')[0].lower() in {'text/csv','text/tab-separated-values','text/plain','application/octet-stream'}:
        text=data.decode('utf-8-sig')
        if '\x00' in text:raise ValueError('Binary data cannot be previewed as a spreadsheet')
        rows=[]
        for index,row in enumerate(csv.reader(io.StringIO(text),delimiter='\t' if suffix=='tsv' else ',')):
            if index>=MAX_ROWS:break
            rows.append([_literal(cell) for cell in row[:MAX_COLS]])
        return {'format':'spreadsheet','sheets':[{'name':name,'rows':rows}],'limits':{'rows':MAX_ROWS,'columns':MAX_COLS,'cell_characters':MAX_TEXT},'notice':'Bounded literal cells only. Formulas and links are not evaluated; rows, columns and long cells may be truncated.'}
    if suffix!='xlsx' or mime.split(';')[0].lower() not in {'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/zip','application/octet-stream'}:
        raise ValueError('This format has no supported literal spreadsheet preview')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos=archive.infolist()
        if len(infos)>128 or sum(i.file_size for i in infos)>MAX_EXPANDED or len({i.filename for i in infos})!=len(infos):raise ValueError('Spreadsheet archive exceeds preview bounds or has ambiguous entries')
        if any(i.flag_bits&1 or i.file_size>MAX_XML or i.file_size>max(i.compress_size,1)*200 for i in infos):raise ValueError('Spreadsheet compressed content is unsupported or exceeds preview bounds')
        def read(path):
            with archive.open(path) as stream:
                value=stream.read(MAX_XML+1)
            return _xml(value)
        workbook=read('xl/workbook.xml');relations=read('xl/_rels/workbook.xml.rels')
        targets={r.attrib.get('Id'):r.attrib.get('Target','') for r in relations if r.attrib.get('TargetMode')!='External' and r.attrib.get('Type','').endswith('/worksheet')}
        strings=[]
        if 'xl/sharedStrings.xml' in archive.namelist():
            for item in read('xl/sharedStrings.xml').findall(f'{{{S}}}si'):
                if len(strings)>=10000:raise ValueError('Spreadsheet shared strings exceed preview bounds')
                strings.append(_literal(''.join(item.itertext())))
        sheets=[]
        for sheet in workbook.findall(f'{{{S}}}sheets/{{{S}}}sheet')[:MAX_SHEETS]:
            target=targets.get(sheet.attrib.get(f'{{{R}}}id'))
            if not target:continue
            path=posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
            if not path.startswith('xl/worksheets/') or not path.endswith('.xml'):raise ValueError('Unsupported worksheet relationship')
            doc=read(path);rows=[];row_numbers=[]
            for row in doc.findall(f'{{{S}}}sheetData/{{{S}}}row')[:MAX_ROWS]:
                number=row.attrib.get('r','')
                if not number.isdecimal() or not 1<=int(number)<=1048576:raise ValueError('Invalid spreadsheet row reference')
                row_numbers.append(int(number))
                values=['']*MAX_COLS
                for cell in row.findall(f'{{{S}}}c')[:MAX_COLS]:
                    ref=re.fullmatch(r'([A-Z]{1,3})[1-9][0-9]*',cell.attrib.get('r',''))
                    if not ref:continue
                    col=0
                    for letter in ref[1]:col=col*26+ord(letter)-64
                    if not 1<=col<=MAX_COLS:continue
                    kind=cell.attrib.get('t');value=cell.findtext(f'{{{S}}}v') or ''
                    if kind=='s':
                        if not value.isdecimal() or not 0<=int(value)<len(strings):raise ValueError('Invalid spreadsheet string reference')
                        value=strings[int(value)]
                    elif kind=='inlineStr':value=''.join(cell.itertext())
                    values[col-1]=_literal(value)
                rows.append(values)
            sheets.append({'name':_literal(sheet.attrib.get('name','Sheet')),'rows':rows,'row_numbers':row_numbers})
        return {'format':'spreadsheet','sheets':sheets,'limits':{'sheets':MAX_SHEETS,'rows':MAX_ROWS,'columns':MAX_COLS,'cell_characters':MAX_TEXT},'notice':'Bounded saved cell values only. Formulas, macros and external links are not evaluated or fetched; values may be stale or truncated.'}
