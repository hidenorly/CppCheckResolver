#   Copyright 2024 hidenorly
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import argparse
import os
import sys
import json
import select
from GptHelper import GptClientFactory, IGpt, GptQueryWithCheck
from ExecUtil import ExecUtil
from JsonCache import JsonCache

class CppCheckerUtil:
    def __init__(self, cppchecker_path):
        self.cppchecker_path = cppchecker_path

    def parse_line(self, line):
        filename = None
        line_number = None
        message_id = None
        message = None
        commit_id = None
        the_line = None

        if line.startswith("| "):
            cols = line.split(" | ")
            if len(cols)==6:
                filename = cols[0][2:]
                try:
                    line_number = int(cols[1])
                except:
                    pass
                message_id = cols[2].strip()
                message = cols[3]
                commit_id = cols[4]

                line = cols[5]
                pos = line.find("```")
                if pos!=None:
                    pos2 = line.find("```", pos+3)
                    if pos2!=None:
                        the_line = line[pos+3:pos2]

        if filename=="filename" or filename==":---":
            filename=None
        if message==":---" or message=="message":
            message=None
        if message_id==":---" or message_id=="id":
            message_id=None
        if commit_id==":---" or commit_id=="commitId":
            commit_id=None
        if the_line=="-- " or the_line=="eLine ":
            the_line=None

        return filename, line_number, message_id, message, commit_id, the_line

    def parse_result(self, lines, target_path=None):
        result = {}

        for line in lines:
            filename, line_number, message_id, message, commit_id, the_line = self.parse_line(line)
            #print(f'{filename}, {line_number}, {message_id}, {message}, {commit_id}, {the_line}')
            if filename and line_number and message_id and message:
                if not target_path or os.path.exists(os.path.join(target_path, filename)):
                    if not filename in result:
                        result[filename] = {}
                    if not line_number in result[filename]:
                        result[filename][line_number] = {}
                    if not message_id in result[filename][line_number]:
                        result[filename][line_number][message_id] = []
                    result[filename][line_number][message_id].append(message)

        return result


    def execute(self, target_path):
        exec_cmd = f'ruby {self.cppchecker_path} {target_path} -m detail -s --detailSection=\"filename|line|id|message|commitId|theLine\"'

        result = self.parse_result(ExecUtil.getExecResultEachLine(exec_cmd, target_path, False), target_path)

        return result


class CppCheckerResolverWithLLM(GptQueryWithCheck):
    PROMPT_FILE = os.path.join(os.path.dirname(__file__), "cppcheck_resolver.json")

    def __init__(self, client=None, promptfile=None):
        if not promptfile:
            promptfile = self.PROMPT_FILE
        super().__init__(client, promptfile)

    def is_ok_query_result(self, query_result):
        # TODO: IMPROVE THIS
        query_result = str(query_result).strip()
        if not query_result:
            return False
        return True

    def query(self, lines, relative_pos, message):
        if isinstance(lines, list):
            lines = "\n".join(lines)

        replace_keydata={
            "[CPPCHECK]": message,
            "[RELATIVE_POSITION]": relative_pos,
            "[TARGET_LINES]": lines,
        }
        return super().query(replace_keydata)


class CppCheckerResolver:
    CACHE_ID = "CppCheckerResolver"

    def __init__(self, resolver, margin_lines=10):
        self.resolver = resolver
        self.margin_lines = margin_lines
        self.cache = JsonCache(os.path.join(JsonCache.DEFAULT_CACHE_BASE_DIR, self.CACHE_ID),  JsonCache.CACHE_INFINITE)

    def reset_cache(self):
        self.cache.clearAllCache(self.CACHE_ID)


    def extract_target_lines(self, lines, target_line, margin_lines=None):
        if margin_lines==None:
            margin_lines = self.margin_lines
        start_pos = max(target_line-margin_lines, 0)
        end_pos = min(target_line+margin_lines, len(lines))
        target_lines = "\n".join(lines[start_pos:end_pos])
        return target_lines, target_line-start_pos

    def cut_off_string(self, input_string, max_length):
        input_string_length = len(input_string)
        input_string_length = min(input_string_length, max_length)
        return input_string[0:input_string_length]

    MAX_FILENAME_LENGTH = 240
    BUDGET_FILENAME_LENGTH = 128

    def get_cache_identifier(self, filename, lines, target_line, report):
        target_lines, relative_pos = self.extract_target_lines(lines, target_line, 3)

        allowed_length = max(self.MAX_FILENAME_LENGTH-len(filename), 0)
        if allowed_length==0:
            filename = self.cut_off_string(filename, self.BUDGET_FILENAME_LENGTH)
            allowed_length = self.MAX_FILENAME_LENGTH - self.BUDGET_FILENAME_LENGTH

        target_lines = self.cut_off_string(target_lines, int(allowed_length*0.8))
        report = self.cut_off_string(report, int(allowed_length*0.2))

        uri = filename + ":" + target_lines + ":" + str(relative_pos) + ":" + report

        return uri

    def execute(self, base_dir, filename, reports, is_only_new):
        resolved_outputs = []
        target_path = os.path.join(base_dir, filename)
        lines = IGpt.files_reader(target_path)
        lines = lines.splitlines()

        for line_number, messages in reports.items():
            message_id = "_".join(messages.keys())
            multiple_messages = []
            for _messages in messages.values():
                multiple_messages.extend(_messages)

            uri = self.get_cache_identifier(filename, lines, line_number, message_id)
            resolved_output = self.cache.restoreFromCache(uri)

            if resolved_output==None:
                # no hit in the cache
                flatten_messages = "\n".join(multiple_messages)
                target_lines, relative_pos = self.extract_target_lines(lines, line_number)
                resolved_output, _ = self.resolver.query(target_lines, relative_pos, flatten_messages)
                resolved_output = {"filename": filename, "pos": line_number, "message": flatten_messages, "resolution": resolved_output}
                self.cache.storeToCache(uri, resolved_output )
            elif is_only_new:
                # found in cache & only_new then should omit
                resolved_output = None

            if resolved_output:
                resolved_outputs.append(resolved_output)

        return resolved_outputs


if __name__=="__main__":
    parser = argparse.ArgumentParser(description='CppCheck Resolver')
    parser.add_argument('args', nargs='*', help='target folder or android_home')
    parser.add_argument('--cppcheck', default=os.path.dirname(os.path.abspath(__file__))+"/../CppChecker/CppChecker.rb", help='Specify the path for CppChecker.rb')
    parser.add_argument('-m', '--marginline', default=10, type=int, action='store', help='Specify margin lines')

    parser.add_argument('-c', '--useclaude', action='store_true', default=False, help='specify if you want to use calude3')
    parser.add_argument('-g', '--gpt', action='store', default="openai", help='specify openai or calude3 or openaicompatible')
    parser.add_argument('-k', '--apikey', action='store', default=None, help='specify your API key or set it in AZURE_OPENAI_API_KEY env')
    parser.add_argument('-y', '--secretkey', action='store', default=os.getenv("AWS_SECRET_ACCESS_KEY"), help='specify your secret key or set it in AWS_SECRET_ACCESS_KEY env (for claude3)')
    parser.add_argument('-e', '--endpoint', action='store', default=None, help='specify your end point or set it in AZURE_OPENAI_ENDPOINT env')
    parser.add_argument('-d', '--deployment', action='store', default=None, help='specify deployment name or set it in AZURE_OPENAI_DEPLOYMENT_NAME env')

    parser.add_argument('--reset', action='store_true', default=False, help='specify if you want to reset cache')

    parser.add_argument('--onlynew', action='store_true', default=False, help='specify if you want to report newly found resolution (cache misshit)')

    args = parser.parse_args()

    gpt_client = GptClientFactory.new_client(args)
    llm_resolver = CppCheckerResolverWithLLM(gpt_client)
    resolver = CppCheckerResolver(llm_resolver)
    if args.reset:
        resolver.reset_cache()

    if os.path.exists(args.cppcheck):
        cppchecker = CppCheckerUtil(args.cppcheck)

        for target_path in args.args:
            results = cppchecker.execute(target_path)
            for filename, reports in results.items():
                resolved_outputs = resolver.execute(target_path, filename, reports, args.onlynew)
                resolved_outputs = sorted(resolved_outputs, key=lambda x: (x["filename"], x["pos"]))
                if resolved_outputs:
                    print(f"# {filename}")
                    print("")
                    for resolved_output in resolved_outputs:
                        print(f"## {resolved_output["message"].split("\n")[0]} (line:{resolved_output["pos"]})")
                        print("")
                        print(resolved_output["resolution"])
                        print("")
