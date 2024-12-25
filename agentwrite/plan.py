import requests
import time
import os
import json
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
import numpy as np
import random
import codecs
import argparse
from copy import deepcopy
from tqdm import tqdm
import traceback
import re
import torch.distributed as dist
import torch.multiprocessing as mp

def read_env(env_file='env'):
    """
    读取env文件，将其中的键值对设置为环境变量。
    文件中形如：
       GPT4_API_KEY = 'xxx'
       GPT_MODEL = 'yyy'
       END_POINT = 'zzz'
    """
    if not os.path.exists(env_file):
        print(f"警告：未找到指定的 env 文件: {env_file}")
        return

    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # 跳过空行或注释行
            if not line or line.startswith('#'):
                continue
            # 按第一个 = 分割
            key, val = line.split('=', 1)
            key = key.strip()
            # 去掉 val 两端可能的引号或空格
            val = val.strip().strip('"').strip("'")
            os.environ[key] = val

# 读取 env 文件，设置环境变量
read_env()

# 从环境变量中获取配置
GPT4_API_KEY = os.environ.get('GPT4_API_KEY', None)
GPT_MODEL = os.environ.get('GPT_MODEL', None)
END_POINT = os.environ.get('END_POINT', None)

def get_response_gpt4(prompt, max_new_tokens=1024, temperature=1.0, stop=None):
    """
    调用 GPT-4 接口，获取生成结果
    """
    tries = 0
    while tries < 10:
        tries += 1
        try:
            headers = {
                'Authorization': f"Bearer {GPT4_API_KEY}",
            }
            messages = [
                {'role': 'user', 'content': prompt},
            ]
            resp = requests.post(
                END_POINT,
                json={
                    "model": GPT_MODEL,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_new_tokens,
                    "stop": stop,
                },
                headers=headers,
                timeout=600,
                verify=False
            )
            if resp.status_code != 200:
                raise Exception(resp.text)
            resp = resp.json()
            break
        except KeyboardInterrupt as e:
            raise e
        except Exception as e:
            if "maximum context length" in str(e):
                # 针对上下文过长的特殊报错，直接抛出
                raise e
            elif "triggering" in str(e):
                # 针对合规策略相关
                return 'Trigger OpenAI\'s content management policy'
            print(f"Error Occurs: \"{str(e)}\"        Retry ...")
    else:
        print("Max tries. Failed.")
        return "Max tries. Failed."

    try:
        return resp["choices"][0]["message"]["content"]
    except:
        return ''

def get_pred(rank, world_size, data, max_new_tokens, fout, template):
    for item in tqdm(data):
        prompt = item['prompt']
        prompt = template.replace('$INST$', prompt)
        try:
            response = get_response_gpt4(prompt, max_new_tokens)
            item["plan"] = response
            fout.write(json.dumps(item, ensure_ascii=False)+'\n')
            fout.flush()
        except Exception as e:
            print(e)

def seed_everything(seed):
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.cuda.manual_seed_all(seed)

if __name__ == '__main__':
    # input format: {"prompt": "xxx", ...}
    # output format: {"prompt": "xxx", "plan": "xxx", ...}
    in_file = 'instructions.jsonl'
    out_file = 'plan.jsonl'
    seed_everything(42)
    max_new_tokens = 4096
    world_size = 8

    has_data = {}
    if os.path.exists(out_file):
        with open(out_file, encoding='utf-8') as f:
            has_data = {json.loads(line)["prompt"]: 0 for line in f}

    fout = open(out_file, 'a', encoding='utf-8')
    data = []
    with open(in_file, encoding='utf-8') as f:
        for line in f:
            item = json.loads(line)
            if item["prompt"] not in has_data:
                data.append(item)

    template = open('prompts/plan.txt', encoding='utf-8').read()

    data_subsets = [data[i::world_size] for i in range(world_size)]
    processes = []
    for rank in range(world_size):
        p = mp.Process(
            target=get_pred,
            args=(rank, world_size, data_subsets[rank], max_new_tokens, fout, template)
        )
        p.start()
        processes.append(p)

    for p in processes:
        p.join()
