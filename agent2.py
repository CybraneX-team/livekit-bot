from __future__ import annotations
import logging
import json
import asyncio
from dotenv import load_dotenv
from datetime import datetime
from typing import Annotated
from livekit import api, rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm as LLLLM,
    metrics,
)
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.agents import llm as LLM
from livekit.plugins import google, deepgram, silero, turn_detector
from livekit.plugins.openai import stt, llm, tts
from langdetect import detect



load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("voice-agent")

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

llm_engine = llm.LLM.with_groq(model="llama-3.3-70b-versatile", temperature=0.8,)

def before_tts(text, ctx):
    lang = detect(text)
    print(lang)


async def entrypoint(ctx: JobContext):
    initial_ctx = LLM.ChatContext().append(
        role="system",
        text=(
            
            """ Use casual language with fillers to sound more human.
                Responses should be very short, precise and engaging, just like a real phone call—no long explanations or robotic tone!
                You are Urmi, an assistant for Dr. Ramesh’s Ayurveda, an Ayurvedic clinic with centers in Delhi, Govardhan, and Udupi. The clinic operates from 8 AM to 6 PM daily, but remains closed on Sundays.
                If the user uses Hindi or Kannada, respond with the same language, else stick to English. If the user talks in hinglish (hindi and english mix), strictly talk in hinglish.
                
                Dr. Ramesh is a well-known Ayurvedic practitioner specializing in holistic healing and natural treatments.

                Your role is to assist callers by answering questions about the clinic and booking appointments. When scheduling an appointment, gather necessary details in a warm, casual, and slightly witty manner:

                Ask for their full name.
                Ask about the health issue they need help with (e.g., digestion, stress, joint pain).
                Ask which center they’d like to visit (Delhi, Govardhan, or Udupi).
                Ask for their preferred date and time.
                Confirm all details, including location, date, and time.
                Keep the conversation light, friendly, and natural.
                Responses should be short, precise and engaging, just like a real phone call—no long explanations or robotic tone!
            """
            
        ),
    )

    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for the first participant to connect
    participant = await ctx.wait_for_participant()
    logger.info(f"starting voice assistant for participant {participant.identity}")
    phone_number = participant.identity.split("+")[1]
    logger.info(f"phone number: {phone_number}")

    safe_phone = ''.join(c for c in phone_number if c.isalnum())
    transcription_file = f"transcriptions/transcriptions_{safe_phone}_{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.log"
    logger.info(f"transcription file: {transcription_file}")

    req = api.RoomCompositeEgressRequest(
        room_name=ctx.room.name,
        layout="speaker",
        audio_only=True,
        segment_outputs=[api.SegmentedFileOutput(
            filename_prefix="output",
            playlist_name="my-playlist.m3u8",
            segment_duration=5,
            live_playlist_name="live-playlist.m3u8",
            s3=api.S3Upload(
                access_key="AKIAVGCTBO4DKUH4SKCJ",
                secret="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",
                region="ap-south-1",
                #endpoint="https://sip-bot.s3.ap-south-1.amazonaws.com",
                bucket="sip-bot",
            )
        )]
    )

    lkapi = api.LiveKitAPI()
    res = await lkapi.egress.start_room_composite_egress(req)
    print(res)

    # Using Google TTS instead of Cartesia
    agent = VoicePipelineAgent(
        vad=ctx.proc.userdata["vad"],
        stt=stt.STT.with_groq(model="whisper-large-v3-turbo", detect_language=True),
        llm=llm_engine,
        tts=tts.TTS(
            model="gpt-4o-mini-tts",
            voice="alloy",
        ),
        turn_detector=turn_detector.EOUModel(),
        fnc_ctx=CallActions(api=ctx.api, participant=participant, room=ctx.room),
        # minimum delay for endpointing, used when turn detector believes the user is done with their turn
        min_endpointing_delay=0.3,
        # maximum delay for endpointing, used when turn detector does not believe the user is done with their turn
        max_endpointing_delay=1.0,
        chat_ctx=initial_ctx,
    )

    usage_collector = metrics.UsageCollector()

    @agent.on("metrics_collected")
    def on_metrics_collected(agent_metrics: metrics.AgentMetrics):
        metrics.log_metrics(agent_metrics)
        usage_collector.collect(agent_metrics)

    log_queue = asyncio.Queue()

    @agent.on("user_speech_committed")
    def user_speech_commited(msg: LLM.ChatMessage):
        if isinstance(msg.content, list):
            msg.content = "\n".join(
                "[image]" if isinstance(x, llm.ChatImage) else x for x in msg
            )
        log_queue.put_nowait(f"[{datetime.now()}] USER:\n{msg.content}\n\n")

    @agent.on("agent_speech_committed")
    def on_agent_speech_committed(msg: LLM.ChatMessage):
        log_queue.put_nowait(f"[{datetime.now()}] AGENT:\n{msg.content}\n\n")
    
    async def write_transcription():
        import aiofiles
        async with aiofiles.open(transcription_file, "w", encoding="utf-8") as f:
            while True:
                msg = await log_queue.get()
                if msg is None:
                    break
                await f.write(msg)

    write_task = asyncio.create_task(write_transcription())

    async def finish_queue():
        log_queue.put_nowait(None)
        await write_task

    ctx.add_shutdown_callback(finish_queue)

    agent.start(ctx.room, participant)

    # The agent should be polite and greet the user when it joins :)
    await agent.say("Hello, I am Urmi and this is Dr. Ramesh's Ayurveda Clinic, how can i help you", allow_interruptions=True)

    await lkapi.aclose()

class CallActions(LLLLM.FunctionContext):
    """
    Detect user intent and perform actions
    """

    def __init__(
        self, *, api: api.LiveKitAPI, participant: rtc.RemoteParticipant, room: rtc.Room
    ):
        super().__init__()

        self.api = api
        self.participant = participant
        self.room = room

    async def hangup(self):
        try:
            await self.api.room.remove_participant(
                api.RoomParticipantIdentity(
                    room=self.room.name,
                    identity=self.participant.identity,
                )
            )
        except Exception as e:
            # it's possible that the user has already hung up, this error can be ignored
            logger.info(f"received error while ending call: {e}")

    @LLLLM.ai_callable()
    async def end_call(self):
        """Called when the user wants to end the call"""
        logger.info(f"ending the call for {self.participant.identity}")
        await self.hangup()

    @LLLLM.ai_callable()
    async def look_up_availability(
        self,
        date: Annotated[str, "The date of the appointment to check availability for"],
    ):
        """Called when the user asks about alternative appointment availability"""
        logger.info(
            f"looking up availability for {self.participant.identity} on {date}"
        )
        await asyncio.sleep(3)
        return json.dumps(
            {
                "available_times": ["1pm", "2pm", "3pm"],
            }
        )

    @LLLLM.ai_callable()
    async def confirm_appointment(
        self,
        date: Annotated[str, "date of the appointment"],
        time: Annotated[str, "time of the appointment"],
    ):
        """Called when the user confirms their appointment on a specific date. Use this tool only when they are certain about the date and time."""
        logger.info(
            f"confirming appointment for {self.participant.identity} on {date} at {time}"
        )
        return "reservation confirmed"

    @LLLLM.ai_callable()
    async def detected_answering_machine(self):
        """Called when the call reaches voicemail. Use this tool AFTER you hear the voicemail greeting"""
        logger.info(f"detected answering machine for {self.participant.identity}")
        await self.hangup()

    
if __name__ == "__main__":
    
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            # giving this agent a name of: "inbound-agent"
            agent_name="inbound-agent",
        ),
    )