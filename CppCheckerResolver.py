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
        message = None

        if line.startswith("| "):
            pos = line.find(" | ")
            if pos!=None:
                filename = line[2:pos]
                line = line[pos+3:]
                pos = line.find(" | ")
                if pos!=None:
                    try:
                        line_number = int(line[0:pos])
                    except:
                        pass
                    line = line[pos+3:]
                    pos = line.find(" |")
                    if pos!=None:
                        message = line[0:pos]

        if filename=="filename" or filename==":---":
            filename=None
        if message==":---":
            message=None

        return filename, line_number, message

    def parse_result(self, lines, target_path=None):
        result = {}
        for line in lines:
            filename, line_number, message = self.parse_line(line)
            if filename and line_number and message:
                if not target_path or os.path.exists(os.path.join(target_path, filename)):
                    if not filename in result:
                        result[filename] = []
                    result[filename].append( [line_number, message] )
        return result


    def execute(self, target_path):
        exec_cmd = f'ruby {self.cppchecker_path} {target_path} -m detail -s --detailSection=\"filename|line|message|\"'

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
    def __init__(self, resolver, margin_lines=10):
        self.resolver = resolver
        self.margin_lines = margin_lines
        self.cache = JsonCache(os.path.join(JsonCache.DEFAULT_CACHE_BASE_DIR, "CppCheckerResolver"),  JsonCache.CACHE_INFINITE)

    def extract_target_lines(self, lines, target_line, margin_lines=None):
        if margin_lines==None:
            margin_lines = self.margin_lines
        start_pos = max(target_line-margin_lines, 0)
        end_pos = min(target_line+margin_lines, len(lines))
        target_lines = "\n".join(lines[start_pos:end_pos])
        return target_lines, target_line-start_pos

    def get_cache_identifier(self, lines, target_line):
        target_lines, relative_pos = self.extract_target_lines(lines, target_line, 3)

        target_lines_length = len(target_lines)
        target_lines_length = min(target_lines_length, 200) # tentative value
        target_lines = target_lines[0:target_lines_length]

        uri = filename + ":" + target_lines + ":" + str(relative_pos)

        return uri

    def execute(self, base_dir, filename, reports):
        resolved_outputs = []
        target_path = os.path.join(base_dir, filename)
        print(target_path)
        lines = IGpt.files_reader(target_path)
        lines = lines.splitlines()
        for report in reports:
            uri = self.get_cache_identifier(lines, report[0])
            resolved_output = self.cache.restoreFromCache(uri)
            if resolved_output==None:
                # no hit in the cache
                target_lines, relative_pos = self.extract_target_lines(lines, report[0])
                resolved_output, _ = self.resolver.query(target_lines, relative_pos, report[1])
                self.cache.storeToCache(uri, resolved_output)
            resolved_outputs.append(resolved_output)
            print(resolved_output)
            exit()
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

    args = parser.parse_args()

    gpt_client = GptClientFactory.new_client(args)
    llm_resolver = CppCheckerResolverWithLLM(gpt_client)
    resolver = CppCheckerResolver(llm_resolver)

    if os.path.exists(args.cppcheck):
        cppchecker = CppCheckerUtil(args.cppcheck)

        for target_path in args.args:
            results = cppchecker.execute(target_path)
            for filename, reports in results.items():
                resolved_outputs = resolver.execute(target_path, filename, reports)
                for resolved_output in resolved_outputs:
                    print(resolved_output)
