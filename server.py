#!/usr/bin/python3.6
# -*- coding: utf-8 -*-

import logging
import click
import sys
from aiohttp import web, ClientSession
import json
import socketio
import hashlib
import yaml

import asyncio
import time
import random
import math
import re
import datetime
import hashids
import json

# 配置列表
appConfig = {}

# 平台定义
pls = {"h5": "1", "android": "2", "ios": "2", "pc" : "1"}

# 数据缓存列表
dataCache = {}

# 机器人订单数据
orderConf = None

sio = socketio.AsyncServer(async_mode='aiohttp')
app = web.Application()
sio.attach(app)

# 定时加载数据频率
reloadDataInterval = 300 

# API请求头 
apiHeaders = {"Content-type": "application/json"}

def initVar():
    '''
        初始变量
    '''
    global appConfig, dataCache, orderConf
    for apps in appConfig:
        dataCache[apps] = None

    with open("./runtime/order_conf.json") as f:
        orderConf = json.loads(f.read())

async def loadData():
    '''
        加载远程数据
    '''
    global appConfig, dataCache
    for appId in appConfig:
        url = appConfig[appId]['api'] + '/v2/service/pusherio'
        async with ClientSession() as session:
            async with session.get(url) as r:
                temp = await r.json()
                dataCache[appId] = temp['data']

                # lottery 转换数据格式
                dataCache[appId]['lottery_pid'] = {}
                for t in dataCache[appId]['lottery']:
                    dataCache[appId]['lottery_pid'][t['id']] = t['pid']

                # hall 转换数据格式
                dataCache[appId]['robot'] = {}
                for t in dataCache[appId]['hall']:
                    dataCache[appId]['robot'][t['id']] = t

                # play 转换数据格式
                dataCache[appId]['play_struct'] = {}
                for t in dataCache[appId]['play']:
                    if t['lottery_pid'] not in dataCache[appId]['play_struct']:
                        dataCache[appId]['play_struct'][t['lottery_pid']] = []
                    
                    # t['tags'] = json.loads(t['tags'])
                    dataCache[appId]['play_struct'][t['lottery_pid']].append(t)
                app.logger.info("加载数据完成")

async def reloadData():
    '''
        每5分钟重新加载数据
    '''
    while True:
        await loadData()
        await sio.sleep(reloadDataInterval)

async def testData():
    '''
        测试
    '''
    global appConfig
    while True:
        for appId in appConfig:
            if dataCache[appId] != None:
                app.logger.info("定时打印: %s", dataCache[appId]['st'])
        await sio.sleep(10)

async def sendRobotMessage(appId):
    '''
        发送机器人信息
        @param string appId
    '''
    while True:
        try:
            # 保证配置读取到了才开始发消息
            if dataCache[appId] == None:
                await sio.sleep(3)
                continue

            # 缓存数据
            # cache = {}
            for room in dataCache[appId]['room']:
                try:
                    # 取得room hash key
                    roomHashKey = getRoomHashKey(appId, room['id'])

                    # 取机器人名字
                    userName = getRobotName(dataCache[appId]['robot'][room['hall_id']]['rebot_list'])

                    # 查询当前彩期
                    lotteryNumber = getCurrentLotteryNumber(dataCache[appId]['lottery_info'][str(room['lottery_id'])])
                    if not lotteryNumber:
                        continue

                    # 发送进入房间信息
                    rt = random.randint(1, 10000)
                    if rt > 6000:
                        enterRoomContent = getRobotEnterRoomMessage(userName = userName)
                        await sio.emit(roomHashKey, enterRoomContent, room = roomHashKey)

                    lotteryPid = dataCache[appId]['lottery_pid'][room['lottery_id']]
                    # 发送诙订单信息
                    orderContent = getRobotOrderMessage(userName = userName, 
                                                                lotteryId = room['lottery_id'],
                                                                lotteryNumber = lotteryNumber, 
                                                                roomId = room['id'], 
                                                                lotteryPlayStruct = dataCache[appId]['play_struct'][lotteryPid],
                                                                minMoney = dataCache[appId]['robot'][room['hall_id']]['rebot_min'], 
                                                                maxMoney = dataCache[appId]['robot'][room['hall_id']]['rebot_max'])

                    await sio.emit(roomHashKey, orderContent, room = roomHashKey)

                    # 更新房间人数数据 
                    rt = random.randint(1, 10000)
                    if rt > 8000:
                        await updateRoomOnlineNum(appId, room['id'])
                except Exception as e:
                    app.logger.error(e)
        except Exception as e:
            app.logger.error(e)


        # 随机睡眠时间控制发送频率
        st = random.randint(3, 7)
        await sio.sleep(st)

def replacePos(str, replace):
    '''
        字符串替换
        @param string
        @param string
        @return string
    '''
    if len(str) > 4:
        return str[:2] + replace + str[len(str) - 2:]
    else:
        return str[:2] + replace

def getRobotName(rebotList):
    '''
        取机器人名字
        @param string 机器人列表 1,2,3,4
        @param string
    '''
    robotArr = re.split('[.|,]', rebotList.strip(' .,\n'))
    robotUser = robotArr[random.randint(0, len(robotArr) - 1)]
    return replacePos(robotUser, '***')

def getCurrentLotteryNumber(lotteryInfo):
    '''
        取出当前x期
        @param array x期信息
        @return mixed
    '''
    now = int(time.time())
    for row in lotteryInfo:
        # 彩期内
        if int(row['start_time']) <= now and int(row['end_time']) > now:
            return row['lottery_number']
        
        # 未开盘
        if int(row['start_time']) > now and int(row['end_time']) > now:
            return False
    return False

def getRobotEnterRoomMessage(userName):
    '''
        生成机器人进入房间内容
        @param string 用户名
        @return dict
    '''
    return {
        'messageType': 1,
        'timer': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'userID': 999999,
        'userName': userName
    }

def getRobotOrderMessage(userName, lotteryId, lotteryNumber, roomId, lotteryPlayStruct, minMoney, maxMoney):
    '''
        生成机器人投注内容
        @param string 用户名
        @param integer 彩种ID
        @param integer 彩期号
        @param integer 房间ID
        @param dict 玩法结构
        @param integer 最低金额
        @param integer 最高金额
        @return dict
    '''
    play = lotteryPlayStruct[random.randint(0, len(lotteryPlayStruct) - 1)]
    num = play['tags'][random.randint(0, len(play['tags']) - 1)]['vv']
    num = num[random.randint(0, len(num) - 1)]

    price = random.randint(minMoney, maxMoney)
    price = getBNum(price)
    if price < minMoney:
        price = minMoney

    if price > maxMoney:
        price = maxMoney

    orderConfKey = str(play['play_id']) + '_' + str(num)

    if int(play['play_id']) == 822:
        playNum = str(num) + ',,,,'
    else:
        playNum = str(num)

    sendData = {
        'data': {
            'room_id': roomId,
            'origin': 3,
            'lottery_id': lotteryId,
            'lottery_number': lotteryNumber,
            'play': [{
                'id': play['play_id'],
                'num': playNum,
                'price': price,
                'times': 1,
            }]
        },
        'play_type_name': play['name'],
        'betting_number': playNum,
        'money': price,
    }

    return {
        'messageType': 2,
        'timer': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'userID': 999999,
        'userName': userName,
        # 'userName': 'ROBET',
        'data': {
            'betting_json': json.dumps({'data': sendData['data']}),
            'betting_number': sendData['betting_number'],
            'multi_number': sendData['betting_number'],
            'lottery_number': lotteryNumber,
            'money': sendData['money'],
            'play_type_name': sendData['play_type_name'],
            'multi_numbers': [orderConf[orderConfKey]]
        }
    }

async def updateRoomOnlineNum(appId, roomId):
    '''
        更新房间在线人数 & 清除历史列表数据
        @param string app id
        @param integer room id
    '''
    url = appConfig[appId]['api'] + '/v2/service/pusherio'
    number = random.randint(50, 250)
    async with ClientSession() as session:
        await session.patch(url, headers=apiHeaders, json={"room": {"id": roomId, "number": number}})

def getRoomHashKey(appId, roomId):
    '''
        获取room hash key
        @param string app id
        @param integer room id
        @return string hash string
    '''
    md5 = hashlib.md5()
    hashstr = appId + 'lottery_room' + str(roomId)
    md5.update(hashstr.encode('utf8'))
    return md5.hexdigest()

def getBNum(num):
    '''
        美化数值
        @param integer num
        @return integer
    '''
    num = int(num / 100)
    b = [0, 1, 2, 5, 8]
    if num < 10:
        pass
    elif num < 100:
        num = int(num / 10) * 10 + random.choice(b)
    elif num < 1000:
        num = int(num / 100) * 100 + random.choice(b) * 10
    elif num < 10000:
        num = int(num / 1000) * 1000 + random.choice(b) * 100

    return num * 100

async def pubilsh(request):
    '''
        发送消息
        @param object request
    '''
    output = {
        'code': 0,
        'msg': '成功'
    }

    data = await request.json()
    if not data or 'app_id' not in data or 'timest' not in data or 'sign' not in data or 'content' not in data or 'room' not in data:
        output['code'] = 500
        output['msg'] = 'argument error'

    if str(data['app_id']) not in appConfig:
        output['code'] = 500
        output['msg'] = 'app_id error'
    else:
        appId = str(data['app_id'])

    if output['code'] == 0:
        md5 = hashlib.md5()
        hashstr = str(data['app_id']) + str(data['timest'])
        md5.update(hashstr.encode('utf8'))
        hashstr = md5.hexdigest()
        md5 = hashlib.md5()
        hashstr = str(hashstr) + str(appConfig[appId]['app_secret'])
        md5.update(hashstr.encode('utf8'))
        hashstr = md5.hexdigest()
        if '!1234' != data['sign'] and hashstr != data['sign']:
            output['code'] = 500
            output['msg'] = 'sign error'

    if output['code'] == 0:
        await sio.emit(data['room'], data['content'], room=data['room'])
    return web.Response(text=json.dumps(output), content_type='application/json')

async def index(request):
    return web.Response(text='Hello World!')

app.router.add_get('/', index)

@sio.on('enter room')
async def enterRoom(sid, data):
    '''
        进入房间
        @param string sid 连接标识号
        @param dict
    '''
    if isinstance(data, (str)):
        data = json.loads(data)
    sio.enter_room(sid, data['room'])

@sio.on('leave room')
def leaveRoom(sid, data):
    '''
        离开房间事件
        @param string sid 连接标识号
        @param dict data
    '''
    sio.leave_room(sid, data['room'])

@sio.on('connect')
async def connect(sid, environ):
    '''
        连接事件
        @param string sid 连接标识号
        @param object environ
    '''
    global appConfig
    try:
        appId = environ['aiohttp.request'].query['app_id']
        token = environ['aiohttp.request'].query['token']
        loginId = environ['aiohttp.request'].query['loginId']
        pl = environ['aiohttp.request'].query['pl']
    except Exception as e:
        appId = None
        token = None
        loginId = None
        pl = None
        app.logger.debug(e)

    if appId == None or token == None or loginId == None or pl == None or pl not in pls:
        app.logger.debug('auth arg fail {0} {1} {2} {3} {4}'.format(appId, token, loginId, pl, pl not in pls))
        return False

    if appId not in appConfig:
        app.logger.debug('auth app_id fail {0}'.format(appId))
        return False

    hids = hashids.Hashids(salt=appId + str(appConfig[appId]['app_secret']), min_length=8, alphabet='abcdefghijklmnopqrstuvwxyz')
    userId = hids.decode(token)[0]
    if isinstance(userId, int) and userId > 0:
        return True
    return False

@sio.on('disconnect')
def disconnect(sid):
    '''
        断开连接事件
        @param string sid 连接标识号
    '''
    pass

@click.command()
@click.option('--port', default=9001, help='set listen port')
@click.option('--conf', default='tc', help='run config')
@click.option('--env', default='dev', help='run level dev or prod')
def main(port, conf, env):

    if env == 'dev': 
        # 日志设置
        logging.basicConfig(level=logging.ERROR)
    else:
        logging.basicConfig(level=logging.CRITICAL)

    '''
        启动入口
    '''
    global appConfig
    appList = conf.split(',')
    for apps in appList:
        with open("./runtime/config/"+apps+".yaml") as f:
            temp = yaml.load(f)
            appConfig[temp['app_id']] = temp
        app.logger.info('application listen on {0} {1}'.format(port, apps))

    # 初始化变量值
    initVar()

    # 执行数据加载
    sio.start_background_task(reloadData)

    # 不同的app在不同的线程运行
    for appId in appConfig:
        # 判断是否打开机器人
        if appConfig[appId]['robot']:
            sio.start_background_task(sendRobotMessage, appId)

    # test2
    # sio.start_background_task(testData)

    web.run_app(app, host='0.0.0.0', port=port)


if __name__ == '__main__':
    main()