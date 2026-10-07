"""Deterministic, whole-utterance voice commands; never substring-match motion."""
import re

DESTINATIONS={'厨房':'wp_008','卧室':'wp_009','浴室':'wp_010'}
ROOM_HOMOPHONES={'厨坊':'厨房','卧市':'卧室','卧事':'卧室','浴市':'浴室','浴是':'浴室'}

def correct_room_command(text):
    # Only repair an entire explicit command's room slot. Never fuzzy-match
    # a sentence, remove negations, or interchange two valid destinations.
    match=re.fullmatch(r'((?:请|请你|帮我)?(?:去|前往|导航到|带我去))(厨坊|卧市|卧事|浴市|浴是)(吧)?[。！!]?\s*',text.strip())
    if not match:return text
    return match[1]+ROOM_HOMOPHONES[match[2]]+(match[3] or '')

def route(text):
    question=re.sub(r'[\s，。！？、,.!?！?]', '', text)
    if question in ('找到了吗','找到了没有','找到没有','东西在哪','它在哪里'):
        return ('object_where',None)
    for pattern in (r'(?:请)?告诉我(.{1,30})的位置',r'(.{1,30})(?:在哪里|在哪儿|在哪)',r'找到(.{1,30})了吗',r'(.{1,30})找到了吗'):
        match=re.fullmatch(pattern,question)
        if match and not any(s in match[1] for s in ('不要','然后','还是','或者')):
            return ('object_where',match[1])
    if '?' in text or '？' in text:return None
    text=re.sub(r'[\s，。！？、,.!?！?]', '', text)
    if text in ('结束对话','结束聊天','先这样','不用了','安静等待'):
        return ('conversation_end',None)
    if text in ('来找我','过来找我','来找找我','找到我','过来'):
        return ('come_find_me',None)
    bring=re.fullmatch(r'(?:请|请你|帮我)?(?:带我去|带我过去|带我去看看|去刚才找到的地方)(?:吧)?',text)
    if bring:
        return ('object_bring',None)
    for pattern in (r'(?:请|请你)?带我(?:去找|去看看|过去找)(.{1,30}?)(?:吧)?',r'(?:请|请你)?带我去(.{1,30}?)(?:的位置|那里)(?:吧)?'):
        match=re.fullmatch(pattern,text)
        if match and not any(s in match[1] for s in ('不','别','然后','并且','还是','或者','能不能','吗','？','?')):
            return ('object_bring',match[1])
    if text in ('取消带路','停止带路'):
        return ('patrol_stop',None)
    if text in ('开始巡航','开始巡航一遍','开始巡航记忆','开始巡航识别','巡航并记住物品','开始巡航录像','巡航录像','开始巡逻录像') or re.fullmatch(r'开始(?:巡航|巡逻)(?:一遍|录像|识别|记忆)?',text):
        return ('patrol_start',None)
    if text in ('停止巡航','结束巡航','停止巡航录像','停止查找','取消查找') or re.fullmatch(r'(?:停止|结束|取消)(?:巡航|巡逻)(?:录像)?',text):
        return ('patrol_stop',None)
    match=re.fullmatch(r'(?:请|请你|我要|我想)?(?:帮我找一下|帮我找找|帮我找|查找|寻找|找一下|找找|找)(.{1,30}?)(?:吧)?',text)
    if match and not any(s in match[1] for s in ('不要','别','然后','并且','还是','或者','能不能','吗')):
        return ('find_object',match[1])
    if text in ('停止','停车','停止导航','取消导航','停下','停下来'):
        return ('stop', None)
    if text in ('跟着我','跟我走','露卡跟着我','露卡跟我走','开始跟随','开始跟着我','请跟着我走','请跟我走','我是主人请跟着我走'):
        return ('follow_start', None)
    if text in ('停止跟随','别跟着我','不要跟了','结束跟随','别跟了','露卡停止跟随'):
        return ('follow_stop', None)
    match=re.fullmatch(r'(?:请|请你|帮我|我要|我想|让小车|让露卡|小车)?(?:去|到|前往|导航到|带我去)(厨房|卧室|浴室)(?:吧)?',text)
    if match:return ('navigate',DESTINATIONS[match.group(1)])
    return None

def hold_level(noise,peak):
    # Modest peak-relative gate handles fluctuating USB background noise.
    # Cap prevents loud syllables from making normal quiet speech disappear.
    return max(0.0025,noise*1.6,min(0.025,peak*0.12))

def destination_intent(text,destinations):
    text=re.sub(r'[\s，。！、,.!]', '', text)
    if text in ('有哪些目的地','你能去哪里','可以去哪里','列出航点','有哪些航点'):
        return ('destination_list',None)
    match=re.fullmatch(r'(?:请|请你|帮我)?(?:去|前往|导航到|带我去|带我到)(.{1,40}?)(?:吧)?',text)
    if not match or any(w in match[1] for w in ('不要','别','然后','或者','还是','吗','？','?')):return None
    hits=[d for d in destinations if d['display_name']==match[1]]
    if len(hits)>1:return ('destination_error','有多个同名目的地，请在客户页面改成不同名称后再试。')
    if len(hits)==1:return ('navigate',hits[0]['id'])
    if match[1] in ('看看','过去','刚才找到的地方'):return None
    return ('destination_error','没有找到已确认的目的地“'+match[1]+'”，请先在客户页面保存并确认。')
