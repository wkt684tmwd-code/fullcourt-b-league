#!/usr/bin/env python3
"""Build Kawasaki game analytics from B.LEAGUE public game contexts (unofficial adapter)."""
import datetime as dt
import json
import logging
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo
from update_stats import table_rows, game_dates, get_adapter, normalize_name, SEASON, ROOT, save_atomic
from sportsdataverse.basketball.bleague import bleague_pbp, bleague_player_box

OUTPUT = ROOT / 'site' / 'kawasaki' / 'data.json'
LOG = logging.getLogger('kawasaki')

def analyze(row, events, box):
    key = str(row['schedule_key'])
    home = normalize_name(row.get('home_team')) == '川崎'
    tid = str(row['home_team_id' if home else 'away_team_id'])
    opponent = str(row['away_team' if home else 'home_team'])
    final = [int(row['home_score' if home else 'away_score']), int(row['away_score' if home else 'home_score'])]
    players = {}
    for p in box:
        if p.get('category') == 1 and p.get('period_category') == 18 and str(p.get('team_id')) == tid and p.get('player_id') is not None:
            pid = str(p['player_id'])
            players[pid] = {'id':pid, 'name':str(p.get('player_name_j') or pid), 'no':str(p.get('player_no') or ''), 'starter':bool(p.get('starter')), 'boxSeconds':int(p.get('seconds_played') or 0), 'boxPlusMinus':p.get('plus_minus')}
    active = {p['id'] for p in players.values() if p['starter']}
    if not events or not players:
        raise ValueError('Missing official play-by-play or box score')
    events = sorted(events,key=lambda e:(int(e['period']),int(e['event_no'])))
    last_period = max(int(e['period']) for e in events)
    duration = 2400 + max(0,last_period-4)*300
    score = [0,0]
    last = 0
    segments = []
    points = [{'t':0,'for':0,'against':0}]
    changes = []
    unknown = 0
    unknown_points = 0
    warnings = []
    def segment(t, delta=(0,0)):
        nonlocal last, unknown, unknown_points
        if t < last:
            raise ValueError('Nonmonotonic game clock')
        seconds = t-last
        if len(active) == 5 and active <= players.keys():
            ids = sorted(active)
            if segments and segments[-1]['players']==ids and segments[-1]['end']==last:
                s=segments[-1]; s['end']=t; s['for']+=delta[0]; s['against']+=delta[1]
            elif seconds or any(delta):
                segments.append({'start':last,'end':t,'players':ids,'for':delta[0],'against':delta[1]})
        else:
            unknown += seconds
            unknown_points += sum(abs(x) for x in delta)
        last=t
    for e in events:
        period=int(e['period'])
        clock=e.get('clock_seconds')
        if clock is None:
            if int(e.get('action_code') or 0) in (86,87,89) or e.get('home_score') is not None:
                warnings.append('Event missing clock')
            continue
        length=600 if period<=4 else 300
        t=(period-1)*600 if period<=4 else 2400+(period-5)*300
        t+=length-int(clock)
        if not 0<=int(clock)<=length:
            raise ValueError('Clock outside period')
        hs,aw=e.get('home_score'),e.get('away_score')
        new=[int(hs),int(aw)] if home and hs is not None and aw is not None else [int(aw),int(hs)] if hs is not None and aw is not None else score[:]
        delta=[new[i]-score[i] for i in (0,1)]
        if any(x<0 for x in delta):
            warnings.append('Score correction in feed')
        segment(t,delta)
        if new!=score:
            score=new
            points.append({'t':t,'for':score[0],'against':score[1]})
        code=int(e.get('action_code') or 0)
        if str(e.get('team_id')) == tid and code in (86,87,89):
            pid=str(e.get('player_id'))
            if code in (87,89):active.discard(pid)
            if code==86:active.add(pid)
            if code==89:active.add(str(e.get('player2_id')))
            changes.append({'t':t,'period':period,'clock':str(e.get('rest_time') or ''),'action':code,'player':pid,'player2':str(e.get('player2_id') or '')})
    segment(duration)
    if score!=final:
        raise ValueError(f'Official final score mismatch: {score} != {final}')
    points.append({'t':duration,'for':score[0],'against':score[1]})
    lineups={}
    individual=defaultdict(lambda:{'seconds':0,'for':0,'against':0})
    for s in segments:
        k=','.join(s['players'])
        l=lineups.setdefault(k,{'players':s['players'],'seconds':0,'for':0,'against':0})
        seconds=s['end']-s['start']
        l['seconds']+=seconds;l['for']+=s['for'];l['against']+=s['against']
        for pid in s['players']:
            p=individual[pid];p['seconds']+=seconds;p['for']+=s['for'];p['against']+=s['against']
    mismatches=[]
    for pid,p in players.items():
        calc=individual[pid]
        p.update(calc)
        if abs(calc['seconds']-p['boxSeconds'])>5:
            mismatches.append(p['name'])
        pm=p.get('boxPlusMinus')
        if pm is not None and calc['for']-calc['against']!=int(pm):
            warnings.append('Plus/minus mismatch: '+p['name'])
    valid=not unknown and not unknown_points and not mismatches and not warnings
    if mismatches:warnings.append('Playing time mismatch: '+', '.join(mismatches))
    if unknown or unknown_points:warnings.append(f'Unresolved lineup: {unknown}s / {unknown_points} points')
    return {'id':key,'date':str(row['date'])[:10],'opponent':opponent,'home':home,'score':final,'duration':duration,'points':points,'players':list(players.values()),'segments':segments if valid else [],'lineups':list(lineups.values()) if valid else [],'changes':changes,'lineupVerified':valid,'warnings':list(dict.fromkeys(warnings)),'source':f'https://www.bleague.jp/game_detail/?ScheduleKey={key}&tab=3','checked':dt.datetime.now(dt.timezone.utc).isoformat()}

def main():
    logging.basicConfig(level=logging.INFO)
    old=json.loads(OUTPUT.read_text(encoding='utf-8')) if OUTPUT.exists() else {'games':[]}
    records={g['id']:g for g in old['games']}
    now=dt.datetime.now(ZoneInfo('Asia/Tokyo')).date()
    adapter=get_adapter()
    errors=[]
    for league,date in game_dates(adapter,now,True,4):
        if league!='premier':continue
        try:
            schedule=table_rows(adapter['bleague_schedule'](season=SEASON,tab=1,month=date.month,day=date.day))
        except Exception as e:
            if type(e).__name__!='NoDataError':errors.append(f'{date}: {e}')
            continue
        for row in schedule:
            if not any(normalize_name(row.get(k))=='川崎' for k in ('home_team','away_team')):continue
            state=str(row.get('state') or '').upper()
            if not ('FINAL' in state or '終了' in state or state in ('END','FINISHED','GAME_END') or (date<now and row.get('home_score') is not None and row.get('away_score') is not None and state not in ('CANCELLED','CANCELED','中止','POSTPONED','延期'))):continue
            if row.get('home_score') is None or row.get('away_score') is None or row['home_score']==row['away_score']:continue
            key=str(row['schedule_key'])
            if key in records and records[key]['lineupVerified'] and (now-date).days>3:continue
            try:
                events=table_rows(bleague_pbp(schedule_key=int(key),season=SEASON))
                box=table_rows(bleague_player_box(schedule_key=int(key),season=SEASON))
                records[key]=analyze(row,events,box)
                LOG.info('Game %s: %s lineup verified=%s',key,records[key]['score'],records[key]['lineupVerified'])
            except Exception as e:
                errors.append(f'{date} {key}: {e}')
                LOG.warning('%s: %s',key,e)
    result={'updated':dt.datetime.now(dt.timezone.utc).isoformat(),'games':sorted(records.values(),key=lambda g:(g['date'],g['id']),reverse=True),'errors':errors}
    save_atomic(OUTPUT,result)
    if not records:raise SystemExit('No Kawasaki official game data obtained')
if __name__=='__main__':main()
