#!/usr/bin/env python3
"""Incremental B.PREMIER / B.ONE 2026-27 season sync.

Unofficial sportsdataverse-py wrappers. Only completed game records are stored.
Public-site use and redistribution conditions should be reviewed by the deployer.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import logging
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'cache' / 'games_2026-27.json'
OUTPUT = ROOT / 'site' / 'data.js'
JST = ZoneInfo('Asia/Tokyo')
SEASON = 2027  # sportsdataverse season = year ENDING the season
START = dt.date(2026, 9, 1)
LEAGUES = {'premier': 1, 'one': 2}
LOG = logging.getLogger('b-stats')
BOX_COUNTS = ['points', 'fg2_made', 'fg2_attempted', 'fg3_made', 'fg3_attempted',
              'ft_made', 'ft_attempted', 'fouls', 'fouls_drawn', 'reb_off', 'reb_def',
              'reb', 'turnovers', 'assists', 'steals', 'blocks', 'blocks_received',
              'ptfb', 'pt2in', 'pt2nd', 'efficiency', 'plus_minus', 'poss']
SUMMARY_COUNTS = ['fg_made', 'fg_attempted', 'fg2_made', 'fg2_attempted',
                  'fg3_made', 'fg3_attempted', 'ft_made', 'ft_attempted',
                  'reb_off', 'reb_def', 'reb', 'assists', 'turnovers', 'steals',
                  'blocks', 'blocks_received', 'fouls', 'fouls_drawn',
                  'paint_points', 'points_off_turnover', 'second_chance_points',
                  'fast_break_points', 'max_lead', 'lead_changes', 'ties']
WEIGHTED_PLAYER = {'usg': 'usg', 'off_rtg': 'player_off_rtg',
                   'def_rtg': 'player_def_rtg', 'net_rtg': 'player_net_rtg'}

# League and division defaults are from official standings on 2026-11-16/17.
# Used only to label clubs; never to fabricate statistical values.
DIVISIONS = {
 'premier': {
  '東地区': 'A東京 仙台 群馬 東京SR 北海道 茨城 富山 千葉J 宇都宮 横浜BC A千葉 川崎 秋田'.split(),
  '西地区': '名古屋D 広島 三河 三遠 京都 琉球 島根 滋賀 信州 長崎 神戸 佐賀 大阪'.split(),
 },
 'one': {
  '北地区': '越谷 岩手 福島 青森 山形'.split(),
  '東地区': '埼玉 立川 東京U 八王子 東京Z'.split(),
  '中地区': '横浜EX 新潟 福井 金沢 岐阜'.split(),
  '西地区': '徳島 岡山 FE名古屋 静岡 奈良'.split(),
  '南地区': '熊本 香川 福岡 愛媛 鹿児島'.split(),
 },
}
ALIASES = {
 'A東京': ['アルバルク東京'], '仙台':['仙台'], '群馬':['群馬'],
 '東京SR':['サンロッカーズ東京','東京SR','サンロッカーズ渋谷'],
 '北海道':['北海道'], '茨城':['茨城'], '富山':['富山'],
 '千葉J':['千葉ジェッツ'], '宇都宮':['宇都宮'],
 '横浜BC':['横浜ビー・コルセアーズ','横浜BC'],
 'A千葉':['アルティーリ千葉','A千葉'], '川崎':['川崎'], '秋田':['秋田'],
 '名古屋D':['名古屋ダイヤモンドドルフィンズ','名古屋D'], '広島':['広島'],
 '三河':['シーホース三河','三河'], '三遠':['三遠'], '京都':['京都'],
 '琉球':['琉球'], '島根':['島根'], '滋賀':['滋賀'], '信州':['信州'],
 '長崎':['長崎'], '神戸':['神戸'], '佐賀':['佐賀'], '大阪':['大阪'],
 '越谷':['越谷'], '岩手':['岩手'], '福島':['福島'], '青森':['青森'],
 '山形':['山形'], '埼玉':['さいたまブロンコス','埼玉'], '立川':['立川'],
 '東京U':['東京ユナイテッド','東京U'], '八王子':['八王子'],
 '東京Z':['アースフレンズ東京Z','東京Z'],
 '横浜EX':['横浜エクセレンス','横浜EX'], '新潟':['新潟'],
 '福井':['福井'], '金沢':['金沢'], '岐阜':['岐阜'],
 '徳島':['徳島'], '岡山':['岡山'],
 'FE名古屋':['ファイティングイーグルス名古屋','FE名古屋'],
 '静岡':['静岡'], '奈良':['奈良'], '熊本':['熊本'], '香川':['香川'],
 '福岡':['福岡'], '愛媛':['愛媛'], '鹿児島':['鹿児島'],
}


def normalize_name(name: str) -> str:
    name = str(name or '').replace('　', ' ').strip()
    for short, candidates in ALIASES.items():
        if name == short or any(candidate in name for candidate in candidates):
            return short
    return name


def division(league: str, name: str) -> str:
    n = normalize_name(name)
    for key, names in DIVISIONS[league].items():
        if n in names:
            return key
    return '地区未確認'


def n(x):
    if x is None or isinstance(x, bool):
        return None
    try:
        f = float(x)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def cleaned_count(x):
    v=n(x)
    return int(v) if v is not None and v.is_integer() else v


def table_rows(frame):
    if hasattr(frame, 'to_dicts'):
        return frame.to_dicts()
    if hasattr(frame, 'to_dict'):
        return frame.to_dict(orient='records')
    if isinstance(frame, list):
        return frame
    return []


def slim_stats(row, keys):
    return {k:cleaned_count(row.get(k)) for k in keys if n(row.get(k)) is not None}


def save_atomic(path: Path, payload: Any, *, as_js: bool=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if as_js:
        body = '/* Automatically generated B.LEAGUE 2026–27 data. */\nwindow.BLEAGUE_DATA = '+body+';\n'
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(body, encoding='utf-8')
    os.replace(temp, path)


def read_cache():
    if not CACHE.exists():
        return {'season':SEASON,'games':{},'clubs':{},'lastSuccessfulSync':None}
    data=json.loads(CACHE.read_text(encoding='utf-8'))
    if data.get('season') != SEASON:
        raise ValueError('Cache season does not match 2026–27')
    return data


def get_adapter():
    try:
        from sportsdataverse.basketball.bleague import (
          bleague_schedule, bleague_schedule_days, bleague_schedule_clubs,
          bleague_player_box, bleague_team_summary)
    except ImportError as exc:
        raise SystemExit('Install: pip install --pre "sportsdataverse>=0.2.0b0"') from exc
    return locals()


def game_dates(adapter, now:dt.date, backfill:bool, recent_days:int):
    if not backfill:
        return [(league, START if (date:=now-dt.timedelta(days=days))<START else date)
                for league in LEAGUES for days in range(min(recent_days, (now-START).days+1))]
    pairs=set()
    month=dt.date(START.year,START.month,1)
    while month <= now:
        for league,tab in LEAGUES.items():
            try:
                rows=table_rows(adapter['bleague_schedule_days'](season=SEASON,tab=tab,month=month.month,day=1))
                for item in rows:
                    try:
                        d=dt.date.fromisoformat(str(item['date'])[:10])
                    except (TypeError, ValueError, KeyError):
                        continue
                    if START<=d<=now:
                        pairs.add((league,d))
            except Exception as exc:
                if type(exc).__name__ == 'NoDataError':
                    continue  # The source explicitly says that this month has no game days.
                LOG.warning('Calendar failed: %s/%d: %s', league,month.month,exc)
                # Never silently pretend the month has no games. Fallback enumerates each date.
                for day in range(1,32):
                    try:d=dt.date(month.year,month.month,day)
                    except ValueError:continue
                    if START<=d<=now:pairs.add((league,d))
        month=(month.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
    return sorted(pairs,key=lambda x:(x[1],x[0]))


def completed(row, now:dt.date):
    state=str(row.get('state') or '').strip().upper()
    hs=n(row.get('home_score'));aw=n(row.get('away_score'))
    if hs is None or aw is None:
        return False
    if state in ('FINAL','END','FINISHED','GAME_END','試合終了') or 'FINAL' in state or '終了' in state:
        return True
    try:d=dt.date.fromisoformat(str(row.get('date'))[:10])
    except (TypeError,ValueError):return False
    # A score on a past date is safe even if the page has an unusual result label.
    return d<now and state not in ('CANCELLED','CANCELED','中止','POSTPONED','延期')


def normalize_game(schedule:dict,league:str,players:list,summary:list):
    key=str(schedule['schedule_key'])
    home_id=str(schedule.get('home_team_id') or '')
    away_id=str(schedule.get('away_team_id') or '')
    home_score=cleaned_count(schedule.get('home_score'))
    away_score=cleaned_count(schedule.get('away_score'))
    pr=[]
    for p in players:
        if p.get('category')!=1 or p.get('period_category')!=18:
            continue
        player_id=str(p.get('player_id') or '')
        team_id=str(p.get('team_id') or '')
        if not player_id or team_id not in (home_id,away_id):
            continue
        sec=cleaned_count(p.get('seconds_played'))
        stats=slim_stats(p,BOX_COUNTS)
        # Source per-game impact figures are NOT additive season totals.
        rates={k:n(p.get(k)) for k in WEIGHTED_PLAYER if n(p.get(k)) is not None}
        pr.append({'id':player_id,'teamId':team_id,
                   'name':str(p.get('player_name_j') or p.get('player_name_e') or player_id),
                   'english':str(p.get('player_name_e') or ''),'no':str(p.get('player_no') or ''),
                   'played':sec is not None and sec>0,'starter':bool(p.get('starter')),
                   'seconds':sec or 0,'stats':stats,'rates':rates})
    summaries={}
    for q in summary:
        if q.get('period_category')!=18:
            continue
        tid=str(q.get('team_id') or '')
        if tid not in (home_id,away_id):continue
        summaries[tid]=slim_stats(q,SUMMARY_COUNTS)
    if len(summaries)!=2:
        raise ValueError(f'Game {key}: team summary has {len(summaries)} teams, expected 2')
    if not pr:
        raise ValueError(f'Game {key}: player box is empty')
    if len({x['id']+'-'+x['teamId'] for x in pr}) != len(pr):
        raise ValueError(f'Game {key}: duplicate player rows')
    # Summary lacks points. Populate from final schedule result.
    summaries[home_id]['points']=home_score
    summaries[away_id]['points']=away_score
    return {'id':key,'league':league,'date':str(schedule.get('date',''))[:10],
            'homeId':home_id,'awayId':away_id,'homeName':str(schedule.get('home_team') or ''),
            'awayName':str(schedule.get('away_team') or ''),'homeScore':home_score,
            'awayScore':away_score,'players':pr,'teamStats':summaries,
            'round':str(schedule.get('round_label') or ''),
            'venue':str(schedule.get('venue') or '')}


def collect(adapter,cache:dict,now:dt.date,backfill:bool,recent_days:int,refresh_hours:float):
    errors=[];new_games=0;discovered=0
    days=game_dates(adapter,now,backfill,recent_days)
    LOG.info('Scanning %d league-dates (%s)',len(days),'backfill' if backfill else 'incremental')
    for league,date in days:
        tab=LEAGUES[league]
        try:
            schedules=table_rows(adapter['bleague_schedule'](season=SEASON,tab=tab,month=date.month,day=date.day))
        except Exception as exc:
            if type(exc).__name__ == 'NoDataError':
                continue  # A day without games is normal, not a failed update.
            LOG.warning('Schedule %s %s: %s',league,date,exc)
            errors.append(f'{league} {date} schedule: {exc}')
            continue
        for row in schedules:
            if not completed(row,now):continue
            key=str(row.get('schedule_key') or '')
            if not key or not key.isdigit():continue
            discovered+=1
            old=cache['games'].get(key)
            if old:
                try:
                    last=dt.datetime.fromisoformat(old['checkedAt'])
                    age=(dt.datetime.now(dt.timezone.utc)-last).total_seconds()/3600
                except (ValueError,KeyError,TypeError):age=10000
                # Re-check recently completed games after delay to pick up score corrections.
                if (now-dt.date.fromisoformat(old['date'])).days>2 or age<refresh_hours:
                    continue
            try:
                pid=int(key)
                player_rows=table_rows(adapter['bleague_player_box'](schedule_key=pid,season=SEASON))
                team_rows=table_rows(adapter['bleague_team_summary'](schedule_key=pid,season=SEASON))
                record=normalize_game(row,league,player_rows,team_rows)
                record['checkedAt']=dt.datetime.now(dt.timezone.utc).isoformat()
                cache['games'][key]=record
                new_games+=1
                LOG.info('Stored %s %s %s-%s',league,date,record['homeName'],record['awayName'])
                if new_games%10==0:
                    save_atomic(CACHE,cache)
            except Exception as exc:
                LOG.warning('Game failed %s %s: %s',league,key,exc)
                errors.append(f'{league} game {key}: {exc}')
        # Query a roster-like club filter once, not after every game.
        if date==days[0][1] or (backfill and date.day<=3):
            try:
                for club in table_rows(adapter['bleague_schedule_clubs'](season=SEASON,tab=tab,month=date.month,day=date.day)):
                    tid=str(club.get('team_id') or '')
                    if tid:cache.setdefault('clubs',{})[tid]={'league':league,'name':str(club.get('name') or tid)}
            except Exception as exc:LOG.debug('club filter unavailable: %s',exc)
    LOG.info('Found %d final games; downloaded %d; total cached %d; errors %d',discovered,new_games,len(cache['games']),len(errors))
    return errors,discovered


def sum_columns(target:dict, source:dict,keys):
    for k in keys:
        v=n(source.get(k))
        if v is not None:
            target[k]=target.get(k,0)+v


def estimate_possessions(team_stats:dict)->float|None:
    a=n(team_stats.get('fg2_attempted'));b=n(team_stats.get('fg3_attempted'))
    ft=n(team_stats.get('ft_attempted'));o=n(team_stats.get('reb_off'));to=n(team_stats.get('turnovers'))
    if any(z is None for z in (a,b,ft,o,to)):return None
    return max(0.01,a+b+.44*ft-o+to)


def build_public(cache:dict,errors:list):
    games=sorted(cache['games'].values(),key=lambda x:(x['date'],int(x['id'])))
    if not games:raise ValueError('No completed games; refusing to replace snapshot with empty data')
    clubs={}
    roster={}
    for tid,meta in cache.get('clubs',{}).items():
        clubs[tid]={'id':tid,'league':meta['league'],'name':meta['name'],
                    'division':division(meta['league'],meta['name']),'gp':0,'w':0,'l':0,'stats':{}}
    for g in games:
        home=g['homeId'];away=g['awayId']
        for tid,side in [(home,'home'),(away,'away')]:
            if tid not in clubs:
                name=g['homeName'] if side=='home' else g['awayName']
                clubs[tid]={'id':tid,'league':g['league'],'name':name,
                            'division':division(g['league'],name),'gp':0,'w':0,'l':0,'stats':{}}
            club=clubs[tid]
            # Longer Japanese name from box rows is preferable, but short source works too.
            club['gp']+=1
            won=(g['homeScore']>g['awayScore']) if side=='home' else (g['awayScore']>g['homeScore'])
            club['w']+=int(won);club['l']+=int(not won)
            own=g['teamStats'].get(tid,{})
            opp=g['teamStats'].get(away if side=='home' else home,{})
            sum_columns(club['stats'],own,SUMMARY_COUNTS+['points'])
            for k in ['reb_off','reb_def']:
                z=n(opp.get(k))
                if z is not None:club['stats']['opp_'+k]=club['stats'].get('opp_'+k,0)+z
            club['stats']['opp_points']=club['stats'].get('opp_points',0)+(g['awayScore'] if side=='home' else g['homeScore'])
            poss=estimate_possessions(own);oposs=estimate_possessions(opp)
            if poss is not None and oposs is not None:
                club['stats']['team_possessions']=club['stats'].get('team_possessions',0)+poss
                club['stats']['opp_possessions']=club['stats'].get('opp_possessions',0)+oposs
                # Estimate game pace normalized to a standard 40-minute game.
                secs=sum(p['seconds'] for p in g['players'] if p['teamId']==tid and p['played'])
                duration=secs/5/60 if secs else 40
                club['stats']['pace_possessions']=club['stats'].get('pace_possessions',0)+(poss+oposs)/2*40/max(40,duration)
        for p in g['players']:
            key=p['id']+'@'+p['teamId']
            if key not in roster:
                roster[key]={'id':key,'sourceId':p['id'],'teamId':p['teamId'],
                  'league':g['league'],'name':p['name'],'english':p['english'],'no':p['no'],
                  'gp':0,'gs':0,'minSec':0,'stats':{}}
            target=roster[key]
            target['name']=p['name'] or target['name']
            target['no']=p['no'] or target['no']
            if not p['played']:continue
            target['gp']+=1
            target['gs']+=int(p['starter'])
            target['minSec']+=p['seconds']
            sum_columns(target['stats'],p['stats'],BOX_COUNTS)
            weight=p['seconds']/60
            for src,dst in WEIGHTED_PLAYER.items():
                val=n(p.get('rates',{}).get(src))
                if val is None:continue
                target['stats'][dst+'_weighted']=target['stats'].get(dst+'_weighted',0)+val*weight
                target['stats'][dst+'_minutes']=target['stats'].get(dst+'_minutes',0)+weight
    # Keep zero as zero for metrics only when observed; missing stats stay absent.
    for obj in [*clubs.values(),*roster.values()]:
        obj['stats']={k:round(v,5) if isinstance(v,float) else v for k,v in obj['stats'].items()}
    public_games=[]
    for g in games:
        # Internal last-checked timestamps are not needed on public pages.
        public_games.append({k:v for k,v in g.items() if k!='checkedAt'})
    updated=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    return {
        'meta':{'mode':'live','season':'2026-27','updatedAt':updated,'source':'B.LEAGUE game contexts (via sportsdataverse-py)',
                'sourceUrl':'https://www.bleague.jp/',
                'totalGames':len(public_games),'errors':errors[:30],
                'note':'試合終了後の公開済みデータに基づき同期。レギュラーシーズン対象。'},
        'teams':sorted(clubs.values(),key=lambda x:(x['league'],x['name'])),
        'players':sorted(roster.values(),key=lambda x:(x['league'],x['name'])),
        'games':public_games,
    }


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--backfill',action='store_true',help='Discover game dates from 2026/09/01 to now')
    parser.add_argument('--recent-days',type=int,default=4,help='Number of recent calendar days to scan')
    parser.add_argument('--refresh-hours',type=float,default=3,help='Minimum age before rechecking recent games')
    parser.add_argument('--offline-test',action='store_true',help='Rebuild public JSON from cache; no network')
    args=parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    cache=read_cache()
    errors=[]
    if not args.offline_test:
        adapter=get_adapter()
        today=dt.datetime.now(JST).date()
        backfill=args.backfill or not bool(cache['games'])
        errors,_=collect(adapter,cache,today,backfill,max(1,args.recent_days),args.refresh_hours)
        save_atomic(CACHE,cache)
    if not cache['games']:
        LOG.error('No completed game data; preserving existing initial snapshot. Errors: %s',errors)
        return 2
    public=build_public(cache,errors)
    save_atomic(OUTPUT,public,as_js=True)
    LOG.info('Saved %d teams, %d players, %d games to %s',len(public['teams']),len(public['players']),len(public['games']),OUTPUT)
    return 0 if not errors else 1

if __name__=='__main__':sys.exit(main())