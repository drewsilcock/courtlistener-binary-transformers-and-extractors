import codecs
import datetime
import os
import subprocess
import traceback
import uuid
from distutils.spawn import find_executable

import eyed3
from eyed3 import id3
from seal_rookery import seals_data, seals_root

root = os.path.dirname(os.path.realpath(__file__))
assets_dir = os.path.join(root, "..", "assets")


def get_audio_binary():
    """Get the path to the installed binary for doing audio conversions

    Ah, Linux. Land where ffmpeg can fork into avconv, where avconv can be the
    correct binary for years and years, and where much later, the fork can be
    merged again and avconv can disappear.

    Yes, the above is what happened, and yes, avconv and ffmpeg are pretty much
    API compatible despite forking and them merging back together. From the
    outside, this appears to be an entirely worthless fork that they embarked
    upon, but what do we know.

    In any case, this program finds whichever one is available and then
    provides it to the user. ffmpeg was the winner of the above history, but we
    stick with avconv as our default because it was the one that was winning
    when we originally wrote our code. One day, we'll want to switch to ffmpeg,
    once avconv is but dust in the bin of history.

    :returns path to the winning binary
    """
    path_to_binary = find_executable("avconv")
    if path_to_binary is None:
        path_to_binary = find_executable("ffmpeg")
        if path_to_binary is None:
            raise Exception(
                "Unable to find avconv or ffmpeg for doing "
                "audio conversions."
            )
    return path_to_binary


def convert_mp3(af_local_path):
    """Convert to MP3

    :param af_local_path:
    :return:
    """
    err = ""
    error_code = 0
    av_path = get_audio_binary()
    tmp_path = os.path.join("/tmp", "audio_" + uuid.uuid4().hex + ".mp3")
    av_command = [
        av_path,
        "-i",
        af_local_path,
        "-ar",
        "22050",  # sample rate (audio samples/s) of 22050Hz
        "-ab",
        "48k",  # constant bit rate (sample resolution) of 48kbps
        tmp_path,
    ]
    try:
        _ = subprocess.check_output(av_command, stderr=subprocess.STDOUT)
        file_data = codecs.open(tmp_path, "rb").read()
    except subprocess.CalledProcessError as e:
        file_data = ""
        err = "%s failed command: %s\nerror code: %s\noutput: %s\n%s" % (
            av_path,
            av_command,
            e.returncode,
            e.output,
            traceback.format_exc(),
        )
        error_code = 1
    return file_data, err, error_code, tmp_path


def set_mp3_meta_data(audio_obj, mp3_path):
    """Sets the meta data on the mp3 file to good values.

    :param audio_obj: an Audio object to clean up.
    :param mp3_path: the path to the mp3 to be converted.
    """

    court = audio_obj.docket.court

    # Load the file, delete the old tags and create a new one.
    audio_file = eyed3.load(mp3_path)
    # Undocumented API from eyed3.plugins.classic.ClassicPlugin#handleRemoves
    id3.Tag.remove(
        audio_file.tag.file_info.name,
        id3.ID3_ANY_VERSION,
        preserve_file_time=False,
    )
    audio_file.initTag()
    audio_file.tag.title = best_case_name(audio_obj)
    date_argued = datetime.datetime.strptime(
        audio_obj.docket.date_argued, "%Y-%m-%d"
    )
    audio_file.tag.album = u"{court}, {year}".format(
        court=court.full_name, year=date_argued.year
    )
    audio_file.tag.artist = court.full_name
    audio_file.tag.artist_url = court.url
    audio_file.tag.audio_source_url = audio_obj.download_url
    audio_file.tag.comments.set(
        u"Argued: {date_argued}. Docket number: {docket_number}".format(
            date_argued=date_argued,
            docket_number=audio_obj.docket.docket_number,
        )
    )
    audio_file.tag.genre = u"Speech"
    audio_file.tag.publisher = u"Free Law Project"
    audio_file.tag.publisher_url = u"https://free.law"
    audio_file.tag.recording_date = audio_obj.docket.date_argued

    # Add images to the mp3. If it has a seal, use that for the Front Cover
    # and use the FLP logo for the Publisher Logo. If it lacks a seal, use the
    # Publisher logo for both the front cover and the Publisher logo.
    try:
        has_seal = seals_data[court.pk]["has_seal"]
    except AttributeError:
        # Unknown court in Seal Rookery.
        has_seal = False
    except KeyError:
        # Unknown court altogether (perhaps a test?)
        has_seal = False

    flp_image_frames = [
        3,  # "Front Cover". Complete list at eyed3/id3/frames.py
        14,  # "Publisher logo".
    ]
    if has_seal:
        with open(
            os.path.join(seals_root, "512", "%s.png" % court.pk), "rb"
        ) as f:
            audio_file.tag.images.set(
                3, f.read(), "image/png", u"Seal for %s" % court.short_name
            )
        flp_image_frames.remove(3)

    for frame in flp_image_frames:
        with open(
            os.path.join(
                assets_dir,
                "producer-300x300.png",
            ),
            "rb",
        ) as f:
            audio_file.tag.images.set(
                frame,
                f.read(),
                "image/png",
                u"Created for the public domain by Free Law Project",
            )

    audio_file.tag.save()
    return audio_file


def best_case_name(obj):
    """Take an object and return the highest quality case name possible.

    In general, this means returning the fields in an order like:

        - case_name
        - case_name_full
        - case_name_short

    Assumes that the object passed in has all of those attributes.
    """
    if obj.case_name:
        return obj.case_name
    elif obj.case_name_full:
        return obj.case_name_full
    else:
        return obj.case_name_short
