SOURCES = ('nav', 'follow', 'relocalize', 'recovery')
INPUT_TOPICS = {source: '/luka/motion/' + source for source in SOURCES}
OUTPUT_TOPIC = '/luka/motion/autonomy'
