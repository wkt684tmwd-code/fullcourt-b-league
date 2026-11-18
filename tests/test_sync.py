"""Synthetic records only: no player stats in these tests are claimed to be real."""
import datetime as dt
import importlib.util
from pathlib import Path
SPEC=importlib.util.spec_from_file_location('update_stats',Path(__file__).parents[1]/'scripts'/'update_stats.py')
mod=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(mod)

def fixture_game():
    s={'schedule_key':1,'date':'2026-10-05','home_team_id':'700','away_team_id':'701','home_team':'川崎','away_team':'仙台','home_score':82,'away_score':79}
    a={'category':1,'period_category':18,'team_id':'700','player_id':'p1','player_name_j':'テストA','player_no':'00','seconds_played':1200,'starter':True,'points':20,'fg2_made':4,'fg2_attempted':8,'fg3_made':3,'fg3_attempted':7,'ft_made':3,'ft_attempted':4,'reb':6,'reb_off':2,'reb_def':4,'assists':5,'turnovers':1,'steals':2,'blocks':1,'efficiency':25,'plus_minus':5,'usg':24,'off_rtg':118,'def_rtg':99,'net_rtg':19}
    b={**a,'team_id':'701','player_id':'p2','player_name_j':'テストB','points':19,'plus_minus':-5}
    t={'period_category':18,'team_id':'700','fg2_made':20,'fg2_attempted':40,'fg3_made':8,'fg3_attempted':25,'ft_made':18,'ft_attempted':23,'reb_off':10,'reb_def':28,'reb':38,'assists':20,'turnovers':10,'steals':7,'blocks':2,'second_chance_points':16,'paint_points':40,'fast_break_points':11,'points_off_turnover':14}
    u={**t,'team_id':'701','reb_off':9,'reb_def':25,'second_chance_points':12}
    return mod.normalize_game(s,'premier',[a,b],[t,u])

def test_game_normalizes():
    g=fixture_game()
    assert g['players'][0]['no']=='00'
    assert g['teamStats']['700']['second_chance_points']==16
    assert len(g['players'])==2

def test_aggregation_and_advanced():
    g=fixture_game()
    result=mod.build_public({'games':{'1':g},'clubs':{}},[])
    assert len(result['teams'])==2
    a=next(x for x in result['players'] if x['sourceId']=='p1')
    assert a['gp']==1 and a['gs']==1
    assert a['stats']['points']==20
    assert a['stats']['player_off_rtg_weighted']==2360
    kawasaki=next(x for x in result['teams'] if x['id']=='700')
    assert kawasaki['stats']['second_chance_points']==16
    assert kawasaki['stats']['opp_points']==79
    assert kawasaki['w']==1 and kawasaki['l']==0
    assert len(result['games'])==1

def test_finals_only():
    row={'date':'2026-10-05','home_score':100,'away_score':90,'state':'FINAL'}
    assert mod.completed(row,dt.date(2026,10,5))
    assert not mod.completed({**row,'home_score':None},dt.date(2026,10,5))
    assert not mod.completed({**row,'state':'中止'},dt.date(2026,10,6))

def test_initial_snapshots():
    from sys import path
    path.insert(0,str(Path(__file__).parents[1]/'scripts'))
    from seed_snapshot import snapshot
    data=snapshot()
    assert len([t for t in data['teams'] if t['league']=='premier'])==26
    assert len([t for t in data['teams'] if t['league']=='one'])==25
    assert data['players']==[]