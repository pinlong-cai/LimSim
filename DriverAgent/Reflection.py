import os
import textwrap
import time
from rich import print
from langchain.callbacks import get_openai_callback
from langchain.chat_models import AzureChatOpenAI, ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from tenacity import *
import json
import logger, logging
from typing import Dict
import re

class ReflectionAssistant:
    def __init__(
        self,
        temperature = 0
    ) -> None:
        oai_api_type = os.getenv("OPENAI_API_TYPE")
        if oai_api_type == "azure":
            print("Using Azure Chat API")
            print("[red]Cautious: Using GPT4 now, may cost a lot of money![/red]")
            self.llm = AzureChatOpenAI(
                deployment_name="GPT-4",
                temperature=temperature,
                max_tokens=1000
            )
        elif oai_api_type == "openai":
            self.llm = ChatOpenAI(
                temperature=temperature,
                model_name='gpt-4',
                max_tokens=1000
            )

        self.logger = logger.setup_app_level_logger(logger_name="Reflection", file_name="add_memory.log")
        self.logging = logging.getLogger("Reflection").getChild(__name__)
        self.record_json_file = "./reflection.json"
        self.record_json = {}
        if not os.path.isfile(self.record_json_file):
            with open(self.record_json_file, "w", encoding="utf-8") as f:
                json.dump({"reflection_data": []}, f, indent=4)

    def record(self, content: Dict) -> None:
        with open(self.record_json_file, "r", encoding="utf-8") as f:
            old_data = json.load(f)
            
        old_data["reflection_data"].append(content)
        with open(self.record_json_file, "w", encoding="utf-8") as f:
            json.dump(old_data, f, indent=4)
        return None


    def reflection(self, origin_message: str, llm_response: str, evaluation: str, action: int) -> str:
        self.record_json = {
            "human_question":"",
            "reflection":"",
            "time_cost": 0,
            "llm_use": 0,
            "llm_cost": {
                "prompt_token": 0,
                "completion_tokens": 0,
                "cost(USD)": 0
            },
            "add_memory":False,
            "reflection_action": 0
        }

        delimiter = "####"
        system_message = textwrap.dedent(f"""\
        You are ChatGPT, a large language model trained by OpenAI. Now you are an advanced autonomous driving assistant, your goal is to support drivers in performing safe and efficient driving tasks. Here is a detailed outline of the tasks and steps you will undertake to fulfill this role:

        1. **Decision Analysis**: You will analyze the driver's decision to assess whether they align with safe driving standards and best practices.

        2. **Issue Identification**: If you detect a decision by the driver that may lead to suboptimal outcomes, you will pinpoint the problem, such as a lack of understanding of traffic rules, incorrect judgment of the surrounding environment, or delayed reaction times.

        3. **Correction and Suggestions**: You will provide the correct reasoning process and decision outcomes, for instance, advising when and where to slow down, when to change lanes.

        4. **Feedback and Recommendations**: You will offer immediate feedback and suggestions to the driver to help them improve their driving skills, such as reminders to be aware of blind spots, maintain safe distances, and avoid distractions while driving.

        Through these steps, you will ensure that drivers can complete their driving tasks more safely and efficiently with your assistance. safely and efficiently with your assistance.
        """)


        human_message = f"""\
        ``` Human Message ```
        {origin_message}
        ``` Driver's Decision ```
        {llm_response}
        ``` Evaluation Result ```
        {evaluation}
        The evaluation indicators were calculated as follows, all scores are between 0 and 1:
        - Traffic Light Score: If you go through a red light, the score is 0.7. Otherwise it is 1.0. 
        - Comfort Score: The greater the absolute value of car's acceleration and jerk, the smaller the comfort score.
        - Efficiency Score: The lower the car's speed, the smaller the score.
        - Speed Limit Score: If the car's speed exceeds the speed limit, the score will be less than 1.0. As the portion of the car that exceeds the speed limit gets larger, the score will be lower.
        - Collision Score: When the likelihood of the car colliding with another car is higher, the score is lower. When the score is 1.0, the time in which the car is likely to collide with another car (ttc) is greater than 10 s. When the score is 0.0, the collision has happened.
        - Decision Score: Traffic Light Score * (0.2 * Comfort Score + 0.2 * Efficiency Score + 0.2 * Speed Limit Score + 0.4 * Collision Score)

        ``` Requestion ```
        Now, you know that the driver receives a low score for making this decision, which means there are some mistake in driver's resoning and cause the wrong action.
        Please carefully check every reasoning in Driver's Decision and find out the mistake in the reasoning process of driver, and also output your corrected version of Driver's Decision.

        ``` Your Answer ```
        Your answer should use the following format:
        {delimiter} Analysis of the mistake:
        <Your analysis of the mistake in driver's reasoning process>
        {delimiter} What should driver do to avoid such errors in the future:
        <Your answer>
        {delimiter} Corrected version of Driver's Decision:
        <Your corrected version of Driver's reasoning process and decision outcomes, the format should be same with the Driver's Decision>
        Response to user:{delimiter} <only output one `Action_id` as a int number of you decision, without any action name or explanation. The output decision must be unique and not ambiguous, for example if you decide to decelearate, then output `4`>
        """.replace("        ", "")
        print(human_message)
        self.record_json["human_question"] = human_message
        print("[green bold]Reflection is running ...[/green bold]")

        messages = [
            SystemMessage(content=system_message),
            HumanMessage(content=human_message),
        ]
        start_time = time.time()
        with get_openai_callback() as cb:
            response = self.llm(messages)
        self.record_json["time_cost"] += time.time() - start_time
        self.record_json["llm_use"] += 1
        if cb.successful_requests:
            self.record_json["llm_cost"]["prompt_token"] += cb.prompt_tokens
            self.record_json["llm_cost"]["completion_tokens"] += cb.completion_tokens
            self.record_json["llm_cost"]["cost(USD)"] += cb.total_cost
        print(f"Time taken: {time.time() - start_time:.2f}s")

        self.record_json["reflection"] = response.content
        decision_action = response.content.split(delimiter)[-1]
        try:
            result = int(decision_action)
            if result not in [1, 2, 3, 4, 8]:
                raise ValueError
        except ValueError:
            print("[red bold]--------- Output is not available, checking the output... ---------[/red bold]")
            self.logging.error("The output is illegal!")
            target_phrase = f"{delimiter} Corrected version of Driver's Decision:"
            correct_answer = response.content[response.content.find(
            target_phrase)+len(target_phrase):].strip()
            try:
                result = self.reacquire_answer(correct_answer)
            except:
                self.logging.error("The reflection result is not illegal after 2 trys! Please check the reflection.json and retry it.")
                print("[red bold]The reflection result is not illegal after 2 trys! Please check the reflection.json and retry it.[/red bold]")
                self.record(self.record_json)
                return None, None
            response.content = response.content + f"\n{delimiter} Output checking result: {result}"
        finally:
            self.record_json["reflection_action"] = result
            if result == action:
                self.record_json["add_memory"] = False
                self.record(self.record_json)
                return None, None
            else:
                self.record_json["add_memory"] = True
                self.record(self.record_json)
        return response.content, result
    
    @retry(reraise=True, stop=stop_after_attempt(3))
    def reacquire_answer(self, illegal_answer: str) -> int:
        delimiter = "####"
        check_message = textwrap.dedent(f"""\
            You are a output checking assistant who is responsible for checking the output of another agent.
            
            The output you received is: {illegal_answer}

            Your should just output the right int type of action_id, with no other characters or delimiters.
            i.e. :
            | Action_id | Action Description                                     |
            |--------|--------------------------------------------------------|
            | 3      | Turn-left: change lane to the left of the current lane |
            | 8      | IDLE: remain in the current lane with current speed   |
            | 4      | Turn-right: change lane to the right of the current lane|
            | 1      | Acceleration: accelerate the vehicle                 |
            | 2      | Deceleration: decelerate the vehicle                 |


            You answer format would be:
            {delimiter} <correct action_id within [3,8,4,1,2]>
            """)
        messages = [
            HumanMessage(content=check_message),
        ]
        start_time = time.time()
        with get_openai_callback() as cb:
            check_response = self.llm(messages)
            self.logging.info(f"Output checking result: {check_response.content}")
            print(f"[green bold]Output checking result: {check_response.content}[/green bold]")
            self.record_json["time_cost"] += time.time() - start_time
            self.record_json["llm_use"] += 1
            if cb.successful_requests:
                self.record_json["llm_cost"]["prompt_token"] += cb.prompt_tokens
                self.record_json["llm_cost"]["completion_tokens"] += cb.completion_tokens
                self.record_json["llm_cost"]["cost(USD)"] += cb.total_cost

        pattern = r"[3,8,4,1,2]"
        result_list = re.findall(pattern, check_response.content)
        if len(result_list) > 0:
            return int(result_list[0])
        else:
            raise("The LLM output is wrong")