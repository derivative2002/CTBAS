import time


class OrderManager:
    def __init__(self, api_client, logger):
        self.api_client = api_client
        self.logger = logger

    def place_order(self, side, pos_side, size, stop_loss_price=None):
        endpoint = "/api/v5/trade/order"
        order_data = {
            "instId": "BTC-USDT-SWAP",
            "tdMode": "cross",
            "side": side,
            "ordType": "market",
            "sz": f"{size:.4f}",
            "posSide": pos_side,
        }

        if stop_loss_price is not None:
            order_data["slTriggerPx"] = str(stop_loss_price)
            order_data["slOrdPx"] = str(stop_loss_price)

        response = self.api_client.get_data_with_retry(endpoint, method="POST", data=order_data)
        self.logger.info(f"下单API请求: {order_data}")
        self.logger.info(f"下单API响应: {response}")

        if response and 'data' in response:
            return response['data']
        return None

    def check_order_status(self, order_id, max_retries=5):
        for _ in range(max_retries):
            order_info = self.get_order_info(order_id)
            if order_info and len(order_info) > 0:
                state = order_info[0].get('state', 'unknown')
                if state in ['live', 'partially_filled']:
                    return 'pending'
                elif state == 'filled':
                    return 'filled'
                elif state in ['canceled', 'order_failed']:
                    return 'failed'
            elif order_info is None:
                time.sleep(1)
                continue
            time.sleep(1)
        return 'unknown'

    def get_order_info(self, order_id):
        endpoint = f"/api/v5/trade/order?instId=BTC-USDT-SWAP&ordId={order_id}"
        response = self.api_client.get_data_with_retry(endpoint, method="GET")
        if response and 'data' in response:
            return response['data']
        elif 'code' in response and 'msg' in response:
            self.logger.error(f"获取订单信息失败: {response['msg']} (错误码: {response['code']})")
        return None
