from .utils import *


rpc_session = RpcSession(
    config.item('rpc.host'), 
    config.item('rpc.port'),
    config.item('rpc.token'),
    config.item('rpc.reconnect_interval'),
)


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