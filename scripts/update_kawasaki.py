#!/usr/bin/env python3
"""Build Kawasaki game analytics from B.LEAGUE public game contexts (unofficial adapter)."""
import datetime as dt
import json
import logging
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo
from update_stats import table_rows, get_adapter, normalize_name, SEASON, ROOT, save_atomic
from sportsdataverse.basketball.bleague import bleague_pbp, bleague_player_box, bleague_game_info

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
    # EventNo is the official global sequence; period 0 and game-level markers are not playing time.
    events = sorted(events,key=lambda e:int(e['event_no']))
    last_period = max(int(e['period']) for e in events if e.get('period') is not None and int(e['period']) >= 1 and int(e.get('action_code') or 0) not in (80,81))
    last_period = int(row.get('max_period') or last_period)
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
        code=int(e.get('action_code') or 0)
        period=int(e.get('period') or 0)
        own_sub=str(e.get('team_id')) == tid and code in (86,87,89)
        # Clock-management markers may carry 00:00 before tip-off or a reset
        # clock at a period boundary. They do not change the five on court.
        if code in (80,81,82,83,84,85):
            continue
        hs,aw=e.get('home_score'),e.get('away_score')
        new=[int(hs),int(aw)] if home and hs is not None and aw is not None else [int(aw),int(hs)] if hs is not None and aw is not None else score[:]
        if not own_sub and new==score:
            continue
        if own_sub and code==86 and str(e.get('player_id')) in active and new==score:
            continue  # redundant starter/on-court announcement; no state change
        if period<1:
            if own_sub and code==86 and str(e.get('player_id')) in active:
                continue  # pregame announcement of a confirmed starter
            warnings.append('Playing event outside a period: '+str(e.get('event_no')))
            continue
        length=600 if period<=4 else 300
        clock=e.get('clock_seconds')
        if clock is None or not 0<=int(clock)<=length:
            warnings.append('Missing or invalid event clock: '+str(e.get('event_no')))
            t=last
        else:
            t=((period-1)*600 if period<=4 else 2400+(period-5)*300)+length-int(clock)
        if t<last:
            # Keep sequence and final-score validation. Do not present a
            # rotation as verified when a meaningful event clock reverses.
            warnings.append(f'Clock correction: event {e.get("event_no")} ({t}s < {last}s)')
            t=last
        delta=[new[i]-score[i] for i in (0,1)]
        if any(x<0 for x in delta):
            warnings.append('Score correction in feed')
        segment(t,delta)
        if new!=score:
            score=new
            points.append({'t':t,'for':score[0],'against':score[1]})
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

# First 19 regular-season games: IDs observed in the actual workflow log.
# The date/teams/final score are checked against official game headers.
KNOWN_GAMES = dict(zip(
    '2026-09-26 2026-09-27 2026-10-03 2026-10-04 2026-10-08 2026-10-10 2026-10-16 2026-10-19 2026-10-21 2026-10-24 2026-10-26 2026-10-31 2026-11-01 2026-11-06 2026-11-09 2026-11-11 2026-11-13 2026-11-16 2026-11-18'.split(),
    '506391 506399 506405 506420 506437 506448 506464 506482 506489 506504 506510 506527 506538 506549 506562 506573 506581 506598 506611'.split()))
# Remaining regular-season dates as published on the club's official 2026-27 schedule.
# Update if the club announces rescheduling.
FUTURE_DATES = '2026-12-06 2026-12-12 2026-12-13 2026-12-19 2026-12-20 2026-12-26 2026-12-27 2026-12-30 2027-01-01 2027-01-03 2027-01-22 2027-01-25 2027-01-27 2027-01-30 2027-01-31 2027-02-03 2027-02-05 2027-02-07 2027-02-11 2027-02-15 2027-02-17 2027-03-06 2027-03-07 2027-03-13 2027-03-14 2027-03-17 2027-03-19 2027-03-21 2027-03-24 2027-04-01 2027-04-04 2027-04-06 2027-04-09 2027-04-11 2027-04-13 2027-04-20 2027-04-23 2027-04-25 2027-04-28 2027-04-30 2027-05-02'.split()
def header_row(key, date):
    h=table_rows(bleague_game_info(schedule_key=int(key),season=SEASON))[0]
    official_date=dt.datetime.fromisoformat(str(h['game_datetime']).replace('Z','+00:00'))
    if official_date.tzinfo is None:official_date=official_date.replace(tzinfo=dt.timezone.utc)
    if official_date.astimezone(ZoneInfo('Asia/Tokyo')).date().isoformat()!=date:
        raise ValueError('Official game date mismatch')
    row={'schedule_key':key,'date':date,'max_period':h.get('max_period')}
    for side in ('home','away'):
        row[side+'_team']=h.get(side+'_team_name_j') or h.get(side+'_team_short_name_j')
        row[side+'_team_id']=h[side+'_team_id']
        row[side+'_score']=h[side+'_score']
    if not any(normalize_name(row.get(k))=='川崎' for k in ('home_team','away_team')):
        raise ValueError('Official header does not contain Kawasaki')
    if row['home_score'] is None or row['away_score'] is None or row['home_score']==row['away_score']:
        raise ValueError('Official final score unavailable')
    return row

def main():
    logging.basicConfig(level=logging.INFO)
    old=json.loads(OUTPUT.read_text(encoding='utf-8')) if OUTPUT.exists() else {'games':[]}
    records={g['id']:g for g in old['games']}
    now=dt.datetime.now(ZoneInfo('Asia/Tokyo')).date()
    adapter=get_adapter()
    errors=[]
    candidates={key:date for date,key in KNOWN_GAMES.items()}
    for day in FUTURE_DATES:
        date=dt.date.fromisoformat(day)
        if date>now:continue
        try:
            schedule=table_rows(adapter['bleague_schedule'](season=SEASON,tab=1,month=date.month,day=date.day))
            for row in schedule:
                if not any(normalize_name(row.get(k))=='川崎' for k in ('home_team','away_team')):continue
                state=str(row.get('state') or '').upper()
                if not ('FINAL' in state or '終了' in state or state in ('END','FINISHED','GAME_END')):continue
                if row.get('home_score') is None or row.get('away_score') is None or row['home_score']==row['away_score']:continue
                candidates[str(row['schedule_key'])]=day
        except Exception as e:
            errors.append(f'{date}: {e}')
            LOG.warning('%s: %s',date,e)
    for key,day in candidates.items():
        date=dt.date.fromisoformat(day)
        if date>now:continue
        if key in records and records[key]['lineupVerified'] and (now-date).days>3:continue
        try:
            row=header_row(key,day)
            events=table_rows(bleague_pbp(schedule_key=int(key),season=SEASON))
            box=table_rows(bleague_player_box(schedule_key=int(key),season=SEASON))
            records[key]=analyze(row,events,box)
            LOG.info('Game %s: %s lineup verified=%s warnings=%s',key,records[key]['score'],records[key]['lineupVerified'],records[key]['warnings'])
        except Exception as e:
            errors.append(f'{date} {key}: {e}')
            LOG.warning('%s: %s',key,e)
    result={'updated':dt.datetime.now(dt.timezone.utc).isoformat(),'games':sorted(records.values(),key=lambda g:(g['date'],g['id']),reverse=True),'errors':errors}
    save_atomic(OUTPUT,result)
    if not records:raise SystemExit('No Kawasaki official game data obtained')
if __name__=='__main__':main()
