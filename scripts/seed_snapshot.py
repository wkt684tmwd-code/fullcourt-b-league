"""Initialize the offline view with official, date-stamped standings; no fake player stats."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
P_E=[('A東京',15,4),('仙台',14,4),('群馬',13,4),('東京SR',12,6),('北海道',11,6),('茨城',9,9),('富山',9,9),('千葉J',9,10),('宇都宮',7,9),('横浜BC',7,11),('A千葉',7,12),('川崎',6,12),('秋田',5,13)]
P_W=[('名古屋D',12,2),('広島',14,3),('三河',11,3),('三遠',10,3),('京都',9,7),('琉球',9,8),('島根',7,9),('滋賀',7,10),('信州',6,11),('長崎',6,12),('神戸',4,13),('佐賀',1,15),('大阪',1,16)]
O_N=[('越谷',15,2),('岩手',11,5),('福島',8,9),('青森',4,13),('山形',2,16)]
O_E=[('埼玉',12,4),('立川',11,5),('東京U',12,6),('八王子',7,9),('東京Z',5,13)]
O_C=[('横浜EX',12,4),('新潟',10,6),('福井',7,9),('金沢',6,10),('岐阜',3,14)]
O_W=[('徳島',13,4),('岡山',13,5),('FE名古屋',10,8),('静岡',8,9),('奈良',3,14)]
O_S=[('熊本',10,6),('香川',8,10),('福岡',7,9),('愛媛',7,10),('鹿児島',5,9)]

def snapshot():
    teams=[]
    for league, division, records in [('premier','東地区',P_E),('premier','西地区',P_W),('one','北地区',O_N),('one','東地区',O_E),('one','中地区',O_C),('one','西地区',O_W),('one','南地区',O_S)]:
        for rank,(name,wins,losses) in enumerate(records,1):
            teams.append({'id':f'seed-{league}-{name}', 'league':league,'name':name,'division':division,'rank':rank, 'gp':wins+losses,'w':wins,'l':losses,'stats':{}})
    return {'meta':{'mode':'snapshot','season':'2026-27','updatedAt':None,'standingsAsOf':{'premier':'2026-11-16','one':'2026-11-17'},'sources':['https://www.bleague.jp/standings-stats/?tab=1','https://www.bleague.jp/standings-stats/?tab=2'],'errors':[]},'teams':teams,'players':[],'games':[]}

def write_data(data):
    p=ROOT/'site'/'data.js'
    p.write_text('/* Generated season data. Do not edit manually. */\nwindow.BLEAGUE_DATA = '+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')

if __name__=='__main__':
    data=snapshot();write_data(data);print('Wrote',len(data['teams']),'clubs to site/data.js')