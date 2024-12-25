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
from plan import read_env

# 调用 read_env 函数，从 env 文件里读取配置
read_env()

# 从环境变量中获取配置
GPT4_API_KEY = os.environ.get('GPT4_API_KEY', None)
GPT_MODEL = os.environ.get('GPT_MODEL', None)
END_POINT = os.environ.get('END_POINT', None)

def get_response_gpt4(prompt, max_new_tokens=1024, temperature=1.0, stop=None):
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
                raise e
            elif "triggering" in str(e):
                return 'Trigger OpenAI\'s content management policy'
            print(f"Error Occurs: \"{str(e)}\"        Retry ...")
    else:
        print("Max tries. Failed.")
        return "Max tries. Failed."

    try:
        return resp["choices"][0]["message"]["content"]
    except:
        return ''

def get_pred(rank, world_size, data, max_new_tokens, fout, template, cache_fout, cache_dict):
    for item in tqdm(data):
        try:
            inst = item['prompt']
            plan = item['plan'].strip().replace('\n\n', '\n')
            steps = plan.split('\n')
            text = ""
            responses = []
            # 步骤过多时直接跳过（自行根据需求调整阈值）
            if len(steps) > 50:
                print(plan)
                continue
            
            for step in steps:
                if inst in cache_dict and step in cache_dict[inst]:
                    response = cache_dict[inst][step]
                    responses.append(response)
                    text += response + '\n\n'
                    continue
                prompt = template.replace('$INST$', inst).replace('$PLAN$', plan.strip()) \
                                 .replace('$TEXT$', text.strip()).replace('$STEP$', step.strip())
                response = get_response_gpt4(prompt, max_new_tokens)
                if response == '':
                    break
                # 保存到缓存文件
                cache_fout.write(json.dumps({"prompt": inst, "step": step, "response": response}, ensure_ascii=False) + '\n')
                cache_fout.flush()
                responses.append(response)
                text += response + '\n\n'
            # 如果某次返回空字符串，则跳过
            if response == '':
                continue
            
            item["write"] = responses
            fout.write(json.dumps(item, ensure_ascii=False) + '\n')
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
    # input format: {"prompt": "xxx", "plan": "xxx", ...}
    # output format: {"prompt": "xxx", "plan": "xxx", "write": [...], ...}
    in_file = 'plan.jsonl'
    out_file = 'write.jsonl'
    cache_file = 'write_cache.jsonl'

    seed_everything(42)
    max_new_tokens = 4096
    world_size = 8

    has_data = {}
    if os.path.exists(out_file):
        with open(out_file, encoding='utf-8') as f:
            has_data = {json.loads(line)["prompt"]: 0 for line in f}

    cache_dict = {}
    if os.path.exists(cache_file):
        with open(cache_file, encoding='utf-8') as f:
            for line in f:
                item = json.loads(line)
                if item["prompt"] not in cache_dict:
                    cache_dict[item["prompt"]] = {}
                cache_dict[item["prompt"]][item["step"]] = item["response"]

    fout = open(out_file, 'a', encoding='utf-8')
    cache_fout = open(cache_file, 'a', encoding='utf-8')

    data = []
    with open(in_file, encoding='utf-8') as f:
        for line in f:
            item = json.loads(line)
            if item["prompt"] not in has_data:
                data.append(item)

    template = open('prompts/write.txt', encoding='utf-8').read()

    data_subsets = [data[i::world_size] for i in range(world_size)]
    processes = []
    for rank in range(world_size):
        p = mp.Process(
            target=get_pred, 
            args=(rank, world_size, data_subsets[rank], max_new_tokens, fout, template, cache_fout, cache_dict)
        )
        p.start()
        processes.append(p)

    for p in processes:
        p.join()
