from .utils import *
from .memory import *


# ================ RPC接口定义 ================= #

@dataclass
class Message:
    msg_id: int
    time: datetime
    user_id: int
    self_id: int
    group_id: int
    nickname: str
    msg: list[dict]

rpc_session = RpcSession(
    config.item('rpc.host'), 
    config.item('rpc.port'),
    config.item('rpc.token'),
    config.item('rpc.reconnect_interval'),
)

def rpc_send_group_msg(group_id: int, message: str):
    return rpc_session.call('send_group_msg', group_id, message)

def rpc_query_llm(model: str, prompt: str, messages: list[dict], options: dict):
    return rpc_session.call('query_llm', model, prompt, messages, options)

def rpc_get_group_history_msg(group_id: int, limit: int) -> list[Message]:
    msgs = rpc_session.call('get_group_history_msg', group_id, limit)
    return [Message(
        msg_id=msg['msg_id'],
        time=datetime.fromtimestamp(msg['time']),
        user_id=msg['user_id'],
        self_id=None,
        group_id=group_id,
        nickname=msg['nickname'],
        msg=msg['msg'],
    ) for msg in msgs]

def rpc_get_new_msgs():
    msgs = rpc_session.call('get_new_msgs')
    return [Message(
        msg_id=msg['msg_id'],
        time=datetime.fromtimestamp(msg['time']),
        user_id=msg['user_id'],
        self_id=msg['self_id'],
        group_id=msg['group_id'],
        nickname=msg['nickname'],
        msg=msg['msg'],
    ) for msg in msgs]

def rpc_query_embeddings(texts: list[str]) -> list[list[float]]:
    return rpc_session.call('query_embeddings', texts)



# ================ 处理逻辑 ================= #

file_db = get_file_db("data/autochat/db.json")

@dataclass
class GroupStatus:
    group_id: int
    willingness: float
    
    @staticmethod
    def load(group_id):
        data = file_db.get(f'status_{group_id}', {})
        return GroupStatus(
            group_id=group_id,
            willingness=data.get('willingness', 0.0),
        )
    
    def save(self):
        file_db.set(f'status_{self.group_id}', {
            'willingness': self.willingness,
        })


group_mems: dict[int, MemorySystem] = {}

def get_group_memory_system(group_id: int) -> MemorySystem:
    if group_id not in group_mems:
        group_mems[group_id] = MemorySystem(group_id, data_dir="data/autochat")
    return group_mems[group_id]


image_caption_db = get_file_db("data/autochat/image_captions.json")

async def get_image_caption(image_url: str) -> str:
    pass

async def format_msgs(
    msgs: list[Message], 
    image_caption_limit: int, 
    image_caption_prob: float,
    emotion_caption_limit: int,
    emotion_caption_prob: float,
) -> str:
    pass



# ================ 主聊天逻辑 ================= #

async def chat(msg: Message):
    status = GroupStatus.load(msg.group_id)
    mem = get_group_memory_system(msg.group_id)

    # ---------------- 更新意愿值 ---------------- #
    status.willingness += config.item('chat.willingness_increase_per_msg')
    info(f"收到新消息，当前意愿值: {status.willingness} 消息内容: {msg}")

    reply_rate = min(max(status.willingness, 0.0), 1.0)
    if random.random() > reply_rate:
        return
    info(f"决定回复该消息")

    # ---------------- 消息处理 ---------------- #

    recent_msgs = rpc_get_group_history_msg(msg.group_id, config.item('chat.history_msg_num'))

    
    # ---------------- 获取记忆 ---------------- #

    # 获取事件记忆

    # 获取自身回复记忆
    sm_num = config.item('chat.self_memory_num')
    self_memories = mem.sm_get(sm_num)[-sm_num:] if sm_num > 0 else []

    # 获取用户记忆
    um_num = config.item('chat.user_memory_num')
    user_msg_counts = {}
    for m in recent_msgs:
        user_msg_counts[m.user_id] = user_msg_counts.get(m.user_id, 0) + 1
    top_users = sorted(user_msg_counts.items(), key=lambda x: x[1], reverse=True)[:um_num]
    user_memories: dict[int, UserMemory] = {}
    for user_id, _ in top_users:
        if um := mem.um_get(user_id):
            user_memories[user_id] = um
    
    # ---------------- 获取聊天记录转文本 ---------------- #

    # ---------------- 请求LLM生成回复 ---------------- #

    # ---------------- 发送回复 ---------------- #


    # ---------------- 更新意愿值 ---------------- #
    status.willingness *= config.item('chat.willingness_decay_per_reply')
    status.willingness -= config.item('chat.willingness_decrease_per_reply')
    status.willingness = max(status.willingness, 0.0)
    status.save()

    # ---------------- 更新记忆 ---------------- #


  
# ================ 主循环 ================= #

async def main():
    asyncio.create_task(rpc_session.run(reconnect=True))
    await asyncio.sleep(5)

    # test
    groups = await rpc_session.call('get_group_list')
    info(f"群列表: {groups}")

    group_id = groups[0]['group_id']
    await rpc_session.call('send_group_msg', group_id, "测试消息 from autochat RPC")
    
    history = await rpc_session.call('get_group_history_msg', group_id, 5)
    info(f"历史消息: {history}")

    llm_response = await rpc_session.call('query_llm', "gg:gemini-2.5-flash", "你好", [], {})
    info(f"LLM响应: {llm_response}")

    while True:
        try:
            msgs = await rpc_session.call('get_new_msgs')
            info(msgs)
        except Exception as e:
            error(f"RPC调用失败")
        
        await asyncio.sleep(2)
        

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())