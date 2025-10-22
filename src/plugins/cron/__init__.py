from ..utils import *
from ..llm import ChatSession, get_model_preset, ChatSessionResponse


config = Config('cron.cron')
logger = get_logger('Cron')
file_db = get_file_db('data/cron/cron.json', logger)
cd = ColdDown(file_db, logger)
gbl = get_group_black_list(file_db, logger, 'cron')

# 获取下次提醒时间描述
def get_task_next_run_time_str(group_id, task_id):
    task_job = scheduler.get_job(f"{group_id}_{task_id}")
    if task_job is None:
        return "无下次提醒"
    if task_job.next_run_time is None:
        return "无下次提醒"
    return f"下次: {task_job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')}"

# 获取时间描述
def get_task_time_desc(task):
    param = task['parameters']
    desc = ""
    desc += param.get('year', "*") + " "
    desc += param.get('month', "*") + " "
    desc += param.get('day', "*") + " "
    desc += param.get('hour', "*") + " "
    desc += param.get('minute', "*") + " "
    desc += param.get('second', "*")
    if 'week'           in param: desc += f" w={param['week']}"
    if 'day_of_week'    in param: desc += f" dow={param['day_of_week']}"
    if 'start_date'     in param: desc += f" s={param['start_date']}"
    if 'end_date'       in param: desc += f" t={param['end_date']}"
    return desc

# 获取task描述字符串
def task_to_str(task):
    res = f"【{task['id']}】{'(muted) ' if task['mute'] else ''}\n"
    res += f"创建者: {task['user_id']} 订阅者: {len(task['sub_users'])}人\n"
    res += f"内容: {truncate(task['content'], 64)}\n"
    res += f"时间: {get_task_time_desc(task)}\n"
    res += f"{get_task_next_run_time_str(task['group_id'], task['id'])}\n"
    return res

# 根据ctx查找task
def find_task(ctx: HandlerContext, check_permission=False, raise_exc=True):
    try: task_id = int(ctx.get_args().strip().split()[0])
    except: raise ReplyException("请在命令后输入任务ID")
    group_tasks = file_db.get(f"tasks_{ctx.group_id}", [])
    for task in group_tasks:
        if task['id'] == task_id:
            if check_permission:
                if not check_superuser(ctx.event) and str(task['user_id']) != str(ctx.user_id):
                    raise ReplyException("只有任务创建者或超级用户才能执行该操作")
            return deepcopy(task)
    if raise_exc:
        raise ReplyException(f"任务【{task_id}】不存在")
    return None

# 更新task
def update_task(task):
    group_tasks = file_db.get(f"tasks_{task['group_id']}", [])
    for i in range(len(group_tasks)):
        if group_tasks[i]['id'] == task['id']:
            group_tasks[i] = task
            file_db.set(f"tasks_{task['group_id']}", group_tasks)
            return
    raise Exception(f"任务 {task['id']} 不存在")

# 解析用户指示
async def parse_instruction(group_id, user_id, user_instruction):
    with open('config/cron/system_prompt.txt', 'r', encoding='utf-8') as f:
        system_prompt = f.read()
    system_prompt = system_prompt.format(time=datetime.now().strftime('%Y-%m-%d %H:%M:%S %A'))
    # print(system_prompt)

    session = ChatSession(system_prompt)
    session.append_user_content(user_instruction)

    model_name = get_model_preset('cron')

    max_retries = config.get('max_retries')
    for retry_count in range(max_retries):
        try:
            def process(resp: ChatSessionResponse):
                start = resp.result.find(r"{")
                end = resp.result.rfind(r"}")
                task = loads_json(resp.result[start:end+1])
                params = task['parameters']
                for key in params:
                    params[key] = str(params[key])
                task['group_id'] = group_id
                task['user_id'] = user_id
                task['sub_users'] = [ str(user_id) ]
                task['count'] = 0
                task['mute'] = False
                return task
            return await session.get_response(model_name, process_func=process)
        except Exception as e:
            if retry_count < max_retries - 1:
                logger.warning(f"分析用户指示失败: {e}")
                continue
            else:
                raise

# 添加cron任务
async def add_cron_job(task, verbose=False):
    if verbose:
        logger.info(f"添加cron任务: {task}")

    async def job_func(group_id, task_id):
        try:
            # 找到当前的task
            task = None
            group_tasks = file_db.get(f"tasks_{group_id}", [])
            for i in range(len(group_tasks)):
                if group_tasks[i]['id'] == task_id:
                    task = group_tasks[i]
                    break
            if task is None:
                logger.warning(f"群组 {group_id} 的任务 {task_id} 不存在")
                return
            
            if task['mute']:
                logger.info(f"群组 {group_id} 的任务 {task_id} 已mute")
                return
            
            last_notify_time = task.get('last_notify_time', None)
            if last_notify_time is not None:
                last_notify_time = datetime.fromisoformat(last_notify_time)
                if (datetime.now() - last_notify_time).total_seconds() < 60:
                    logger.warning(f"跳过在60秒内已执行过的群组 {group_id} 的任务 {task_id}")
                    return

            logger.info(f"执行群组 {group_id} 的任务 {task_id} (第 {task['count']} 次)")

            # 发送消息
            bot = get_bot()
            msg = task['content'].format(time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'), count=task['count']) + "\n"
            for user in task['sub_users']:
                msg += f"[CQ:at,qq={user}]"

            msg += f"\n【{task['id']}】{get_task_next_run_time_str(group_id, task_id)}"

            await send_group_msg_by_bot(bot, task['group_id'], msg.strip())

            # 更新count
            task['count'] += 1
            task['last_notify_time'] = datetime.now().isoformat()
            file_db.set(f"tasks_{group_id}", group_tasks)

        except Exception as e:
            logger.print_exc(f"群组 {group_id} 的任务 {task_id} 执行失败: {e}")

    # 添加任务
    scheduler.add_job(job_func, 'cron', args=[task['group_id'], task['id']], **task['parameters'], id=f"{task['group_id']}_{task['id']}")

# 初始化已有的任务
@async_task("初始化cron任务", logger)
async def init_cron_jobs():
    for key in file_db.keys():
        if key.startswith("tasks_"):
            group_id = int(key.split("_")[-1])
            group_tasks = file_db.get(key, [])
            for task in group_tasks:
                try:
                    await add_cron_job(task)
                except Exception as e:
                    logger.print_exc(f"初始化群 {group_id} 的任务 {task['id']} 失败: {e}")
            if len(group_tasks) > 0:
                logger.info(f"初始化群 {group_id} 的 {len(group_tasks)} 个任务完成")

# 删除cron任务
async def del_cron_job(group_id, task_id):
    logger.info(f"删除cron任务: {group_id}_{task_id}")
    if not scheduler.get_job(f"{group_id}_{task_id}"):
        logger.warning(f"任务 {group_id}_{task_id} 不存在")
        return
    scheduler.remove_job(f"{group_id}_{task_id}")

# 从文件数据库中删除cron任务
def del_cron_task_from_file_db(group_id, task_id):
    group_tasks = file_db.get(f"tasks_{group_id}", [])
    for i in range(len(group_tasks)):
        if group_tasks[i]['id'] == task_id:
            del group_tasks[i]
            file_db.set(f"tasks_{group_id}", group_tasks)
            return

# 定期检查过期任务
@repeat_with_interval(60, "定期检查过期任务", logger, start_offset=20)
async def check_expired_tasks():
    for key in file_db.keys():
        if key.startswith("tasks_"):
            group_id = int(key.split("_")[-1])
            group_tasks = file_db.get(key, [])
            for task in group_tasks:
                try:
                    job = scheduler.get_job(f"{group_id}_{task['id']}")
                    if job is None or job.next_run_time is None:
                        await del_cron_job(group_id, task['id'])
                        del_cron_task_from_file_db(group_id, task['id'])
                        logger.info(f"删除过期任务: {group_id}_{task['id']}")

                        bot = get_bot()
                        await send_group_msg_by_bot(bot, group_id, f"cron任务【{task['id']}】过期，已删除")

                except Exception as e:
                    logger.print_exc(f"检查过期任务 {group_id}_{task['id']} 失败: {e}")


# 添加cron任务
cron_add = CmdHandler(["/cron", "/添加提醒", "/cron_add", "/cron add"], logger)
cron_add.check_cdrate(cd).check_wblist(gbl).check_group()
@cron_add.handle()
async def _(ctx: HandlerContext):
    text = ctx.get_args().strip()
    assert_and_reply(text, "请在/cron_add后输入指示")

    task = await parse_instruction(ctx.group_id, ctx.user_id, text)
    logger.info(f"获取cron参数: {task}")
    if 'error' in task:
        return await ctx.asend_reply_msg(f"添加失败: {task['reason']}")
    
    group_id_top = file_db.get(f"group_id_top_{ctx.group_id}", 0)
    task["id"] = group_id_top + 1

    await add_cron_job(task, verbose=True)

    file_db.set(f"group_id_top_{ctx.group_id}", task["id"])

    group_tasks = file_db.get(f"tasks_{ctx.group_id}", [])
    group_tasks.append(task)
    file_db.set(f"tasks_{ctx.group_id}", group_tasks)

    resp = f"添加成功:\n" + task_to_str(task)
    return await ctx.asend_reply_msg(resp.strip())
   

# 删除任务（仅创建者或超级用户）
cron_del = CmdHandler(["/删除提醒", "/cron_del", "/cron del"], logger)
cron_del.check_cdrate(cd).check_wblist(gbl).check_group()
@cron_del.handle()
async def _(ctx: HandlerContext):
    task_id = find_task(ctx, check_permission=True)['id']
    await del_cron_job(ctx.group_id, task_id)
    del_cron_task_from_file_db(ctx.group_id, task_id)
    return await ctx.asend_reply_msg(f"删除任务【{task_id}】成功")


# 清空cron任务（仅超级用户）
cron_clear = CmdHandler(["/清空提醒", "/cron_clear", "/cron clear"], logger)
cron_clear.check_cdrate(cd).check_wblist(gbl).check_group().check_superuser()
@cron_clear.handle()
async def _(ctx: HandlerContext):
    group_tasks = file_db.get(f"tasks_{ctx.group_id}", [])
    for task in group_tasks:
        await del_cron_job(ctx.group_id, task['id'])
    file_db.set(f"tasks_{ctx.group_id}", [])
    return await ctx.asend_reply_msg("清空成功")


# 列出cron任务
cron_list = CmdHandler(["/提醒列表", "/cron_list", "/cron list"], logger)
cron_list.check_cdrate(cd).check_wblist(gbl).check_group()
@cron_list.handle()
async def _(ctx: HandlerContext):
    group_tasks = file_db.get(f"tasks_{ctx.group_id}", [])
    resp = f"本群共有 {len(group_tasks)} 个任务\n"
    for task in group_tasks:
        resp += task_to_str(task)
    return await ctx.asend_reply_msg(resp.strip())


# 订阅cron任务
cron_sub = CmdHandler(["/订阅提醒", "/cron_sub", "/cron sub"], logger)
cron_sub.check_cdrate(cd).check_wblist(gbl).check_group()
@cron_sub.handle()
async def _(ctx: HandlerContext):
    msg = await ctx.aget_msg()
    cqs = extract_cq_code(msg)
    users = [str(ctx.user_id)]
    for_other_user = False
    if 'at' in cqs:
        users = [ str(cq['qq']) for cq in cqs['at'] ]
        for_other_user = True
    task = find_task(ctx, check_permission=for_other_user)

    ok_users, already_users = [], []
    for user in users:
        if user in task['sub_users']:
            already_users.append(user)
        else:
            task['sub_users'].append(user)
            ok_users.append(user)
    update_task(task)

    resp = ""
    if len(ok_users) > 0:
        resp += "添加订阅成功: "
        for user in ok_users:
            resp += await get_group_member_name(ctx.bot, ctx.group_id, user) + " "
        resp += "\n"
    if len(already_users) > 0:
        resp += "已订阅: "
        for user in already_users:
            resp += await get_group_member_name(ctx.bot, ctx.group_id, user) + " "
        resp += "\n"
    logger.info(f"为 {users} 订阅任务 {ctx.group_id}_{task['id']} 成功: 添加订阅成功 {ok_users} 已订阅 {already_users}")
    return await ctx.asend_reply_msg(resp.strip())
        

# 取消订阅cron任务
cron_unsub = CmdHandler(["/取消订阅提醒", "/cron_unsub", "/cron unsub"], logger)
cron_unsub.check_cdrate(cd).check_wblist(gbl).check_group()
@cron_unsub.handle()
async def _(ctx: HandlerContext):
    msg = await ctx.aget_msg()
    cqs = extract_cq_code(msg)
    users = [str(ctx.user_id)]
    for_other_user = False
    if 'at' in cqs:
        users = [ str(cq['qq']) for cq in cqs['at'] ]
        for_other_user = True
    task = find_task(ctx, check_permission=for_other_user)

    ok_users, already_users = [], []
    for user in users:
        if user in task['sub_users']:
            task['sub_users'].remove(user)
            ok_users.append(user)
        else:
            already_users.append(user)
    update_task(task)

    resp = ""
    if len(ok_users) > 0:
        resp += "取消订阅成功: "
        for user in ok_users:
            resp += await get_group_member_name(ctx.bot, ctx.group_id, user) + " "
        resp += "\n"
    if len(already_users) > 0:
        resp += "未订阅: "
        for user in already_users:
            resp += await get_group_member_name(ctx.bot, ctx.group_id, user) + " "
        resp += "\n"
    logger.info(f"为 {users} 取消订阅任务 {ctx.group_id}_{task['id']} 成功: 取消订阅成功 {ok_users} 未订阅 {already_users}")
    return await ctx.asend_reply_msg(resp.strip())

    
# 清空任务订阅者（仅创建者或超级用户）
cron_unsuball = CmdHandler(["/清空提醒订阅", "/cron_unsuball", "/cron unsuball"], logger)
cron_unsuball.check_cdrate(cd).check_wblist(gbl).check_group()
@cron_unsuball.handle()
async def _(ctx: HandlerContext):
    task = find_task(ctx, check_permission=True)
    task['sub_users'] = []
    update_task(task)
    return await ctx.asend_reply_msg("清空成功")


# 查看任务订阅者
cron_sublist = CmdHandler(["/提醒订阅列表", "/cron_sublist", "/cron sublist"], logger)
cron_sublist.check_cdrate(cd).check_wblist(gbl).check_group()
@cron_sublist.handle()
async def _(ctx: HandlerContext):
    task = find_task(ctx, check_permission=False)
    resp = f"任务 {task['id']} 的订阅者:\n"
    for user in task['sub_users']:
        resp += f"{await get_group_member_name(ctx.bot, ctx.group_id, user)}({user})\n"
    return await ctx.asend_reply_msg(resp.strip())

    
# 静音任务（仅创建者或超级用户）
cron_mute = CmdHandler(["/关闭提醒", "/cron_mute", "/cron mute"], logger)
cron_mute.check_cdrate(cd).check_wblist(gbl).check_group()
@cron_mute.handle()
async def _(ctx: HandlerContext):
    task = find_task(ctx, check_permission=True)
    task['mute'] = True
    update_task(task)
    return await ctx.asend_reply_msg("静音成功")
    

# 静音全部任务（仅超级用户）
cron_muteall = CmdHandler(["/关闭所有提醒", "/cron_muteall", "/cron muteall"], logger)
cron_muteall.check_cdrate(cd).check_wblist(gbl).check_group().check_superuser()
@cron_muteall.handle()
async def _(ctx: HandlerContext):
    group_tasks = file_db.get(f"tasks_{ctx.group_id}", [])
    for task in group_tasks:
        task['mute'] = True
    file_db.set(f"tasks_{ctx.group_id}", group_tasks)
    return await ctx.asend_reply_msg("静音全部成功")

    
# 取消静音任务（仅创建者或超级用户）
cron_unmute = CmdHandler(["/开启提醒", "/cron_unmute", "/cron unmute"], logger)
cron_unmute.check_cdrate(cd).check_wblist(gbl).check_group()
@cron_unmute.handle()
async def _(ctx: HandlerContext):
    task = find_task(ctx, check_permission=True)
    task['mute'] = False
    update_task(task)
    return await ctx.asend_reply_msg("取消静音成功")
    

# 查看自己订阅的任务
cron_mysub = CmdHandler(["/我的提醒订阅", "/cron_mysub", "/cron mysub"], logger)
cron_mysub.check_cdrate(cd).check_wblist(gbl).check_group()
@cron_mysub.handle()
async def _(ctx: HandlerContext):
    group_tasks = file_db.get(f"tasks_{ctx.group_id}", [])
    resp = f"您订阅的任务:\n"
    for task in group_tasks:
        if str(ctx.user_id) in task['sub_users']:
            resp += task_to_str(task)
    return await ctx.asend_reply_msg(resp.strip())


# 修改任务文本
cron_edit = CmdHandler(["/修改提醒", "/cron_edit", "/cron edit"], logger)
cron_edit.check_cdrate(cd).check_wblist(gbl).check_group()
@cron_edit.handle()
async def _(ctx: HandlerContext):
    task = find_task(ctx, check_permission=True)
    text = ctx.get_args().strip().split(" ", 1)[1]
    task['content'] = text
    update_task(task)
    return await ctx.asend_reply_msg(f"修改成功")