TOOLS={
 'robot_status':'查询小车服务、任务状态，参数{}',
 'destinations':'列出当前可导航航点，参数{}',
 'follow_status':'查询人体跟随状态，参数{}',
 'follow_start':'开始跟随当前已经选择并通过核验的人，参数{}',
 'follow_stop':'停止人体跟随并停车，参数{}',
 'navigate':'去、回到、带我回已有房间或航点，例如带我回卧室休息。参数{name:航点显示名称}',
 'cancel_all':'停止导航、巡航和找物，参数{}',
 'patrol_start':'按已保存路线巡航一遍，实时识别并保存物体记忆，参数{}',
 'patrol_stop':'停止巡航，保留已保存物体记忆，参数{}',
 'patrol_route':'查看巡航路线，参数{}',
 'patrol_route_set':'设置巡航顺序，参数{names:[航点显示名称,...]，仅原话有停留秒数时添加dwell_s}',
 'find_object':'查询当前地图的物体记忆找物，参数{query:物品名称或基本描述}',
 'object_where':'查询已找到物品的观察位置，参数{query:物品名称，可省略}',
 'object_bring':'仅带用户去已找到的物品处，例如剪刀、水杯；房间名称禁止使用此工具，应选navigate。参数{query:物品名称，可省略}',
 'localization_status':'查询定位状态，参数{}',
 'localization_auto':'停止状态下尝试自动重定位，参数{}',
 'voiceprint_status':'查询声纹录入数量与最近说话人候选，参数{}',
 'music_search':'搜索音乐，参数{query:歌名或歌手}',
 'music_play':'搜索并播放音乐，参数{query:歌名或歌手}',
 'music_pause':'暂停音乐，参数{}',
 'music_resume':'继续播放音乐，参数{}',
 'music_stop':'停止音乐，参数{}',
 'music_status':'查询音乐播放状态，参数{}',
 'music_volume':'设置音乐音量，参数{volume:0到100}',
 'functions_status':'查询各服务状态，参数{}',
 'functions_start':'启动现有小车功能服务，参数{}',
 'camera_find':'识别相机当前画面的物品，参数{query:物品名称}',
 'record_start':'原地开始录像，不导航，参数{}',
 'record_stop':'停止录像并保存，参数{}',
 'record_status':'查询录像和搜索状态，参数{}',
 'voice_volume':'调整说话音量，参数{direction:up或down}',
 'settings_help':'账号、配网、地图房间航点编辑、声纹录入、手动定位、启动重启等操作入口，参数{topic:功能名称}',
}

READ_ONLY={'robot_status','destinations','follow_status','patrol_route','object_where','localization_status','voiceprint_status','music_search','music_status','settings_help','functions_status','record_status'}

TRIGGERS={'functions_start':['启动','开启'], 'follow_start':['跟着','跟随','跟我'], 'follow_stop':['停止','别跟','不要跟','结束跟随'], 'camera_find':['看','识别'], 'record_start':['录像','录制'], 'record_stop':['停止','结束'], 'voice_volume':['声音','音量'], 'navigate':['去','到','前往','导航','带我回','送我回'], 'cancel_all':['停止','停车','停下','取消','急停','别走'],
 'patrol_start':['巡航','巡逻'], 'patrol_stop':['停止','结束','取消'], 'patrol_route_set':['路线','巡航','顺序'],
 'find_object':['找','查找'], 'object_bring':['带我','带路'], 'localization_auto':['重定位','重新定位'],
 'music_play':['播放','放歌','来首','来一首','听','放一首'], 'music_pause':['暂停'], 'music_resume':['继续','恢复'],
 'music_stop':['停止','关闭','关掉','别放'], 'music_volume':['音量','声音']}

def prompt():
 return ("你是露卡的工具选择器，只返回JSON。可用工具：" + ",".join(TOOLS) +
         "。闲聊选chat，含糊请求选clarify；每次只选一个。问能力用settings_help，不执行动作。"
         "导航仅选原话中的已保存航点，房间不用object_bring；找物用find_object，已找到物品带路用object_bring。"
         "不要编造目标或执行否定、假设、引用中的动作。")
