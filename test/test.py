import fastf1
session = fastf1.get_session(2023, 'Monza', 'Q')
session.load()

lap = session.laps.pick_driver('VER').pick_fastest()
tel = lap.get_telemetry()

# 시간 간격 확인
print(tel.columns)
print(tel['X'])
#print(tel["Time"])
