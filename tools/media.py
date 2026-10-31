"""Explicit video processing; the user's input is always read-only."""
from pathlib import Path
import subprocess, json, shutil
from model import require

def executable(name):
    result=shutil.which(name)
    require(result is not None,f'{name} not found. Install FFmpeg and put ffmpeg/ffprobe on PATH.')
    return result

def run(arguments):
    result=subprocess.run(arguments,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding='utf-8',errors='replace')
    if result.returncode: raise ValueError(result.stderr[-6000:])
    return result.stdout

def probe(path, count=False):
    args=[executable('ffprobe'),'-v','error','-show_streams','-show_format','-of','json']
    if count: args+=['-count_frames']
    data=json.loads(run(args+[str(path)]))
    streams=[x for x in data['streams'] if x['codec_type']=='video']
    require(len(streams)==1,'Expected exactly one video stream')
    v=streams[0];a,b=map(int,v['avg_frame_rate'].split('/'));fps=a/b
    duration=float(data['format']['duration'])
    if count and str(v.get('nb_read_frames','')).isdigit(): duration=int(v['nb_read_frames'])/fps
    return {'width':v['width'],'height':v['height'],'fps':fps,'duration':duration,'codec':v['codec_name'],
            'colorSpace':v.get('color_space'),'colorRange':v.get('color_range'),'colorTransfer':v.get('color_transfer'),'colorPrimaries':v.get('color_primaries'),
            'frames':int(v['nb_read_frames']) if str(v.get('nb_read_frames','')).isdigit() else None,
            'audio':any(x['codec_type']=='audio' for x in data['streams'])}

def transcode(source,destination,height=1080):
    width=round(height*16/9)
    metadata=probe(source)
    require(metadata['colorTransfer'] not in ['smpte2084','arib-std-b67'],'HDR source is unsupported: first create an SDR BT.709 source.')
    require(metadata['colorPrimaries'] in [None,'unknown','unspecified','bt709'],'Convert source primaries to SDR BT.709 before importing.')
    matrix={'bt709':'bt709','bt470bg':'bt601','smpte170m':'bt601',None:'bt709','unknown':'bt709','unspecified':'bt709'}.get(metadata['colorSpace'])
    require(matrix is not None,'Unsupported input color matrix; convert to SDR BT.709 first.')
    value_range='pc' if metadata['colorRange']=='pc' else 'tv'
    # 实测 FFmpeg 7.1.1/8.0 按滤镜输出帧的色彩属性设置编码器，忽略 -color_trc 等输出参数；用 setparams 在帧上写明 BT.709，输出参数留给旧版
    run([executable('ffmpeg'),'-v','error','-nostdin','-y','-i',str(source),'-map','0:v:0','-map','0:a?',
         '-vf',f"scale=w='min({width},iw)':h='min({height},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos:in_color_matrix={matrix}:in_range={value_range}:out_color_matrix=bt709:out_range=tv,fps=60,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709",
         '-c:v','libvpx-vp9','-crf','25','-b:v','0','-deadline','good','-cpu-used','5','-row-mt','1','-threads','4',
         '-pix_fmt','yuv420p','-colorspace','bt709','-color_range','tv','-color_trc','bt709','-color_primaries','bt709',
         '-c:a','libopus','-b:a','128k','-map_metadata','-1',str(destination)])
    return probe(destination,count=True)

def pictures(video,folder,time,x=.5,y=.5):
    try:
        from PIL import Image,ImageCms
        from playback_frames import extract_playback_frame
    except ImportError as e:
        raise ValueError('Image processing requires: python -m pip install -r requirements-media.txt') from e
    folder=Path(folder)
    extract_playback_frame(executable('ffmpeg'),video,folder/'still.jpg',time)
    with Image.open(folder/'still.jpg') as im:
        width,height=im.size;cw=min(width,height*3/4);ch=min(height,width*4/3)
        left=(width-cw)*x;top=(height-ch)*y
        cover=im.crop((round(left),round(top),round(left+cw),round(top+ch))).resize((270,360),Image.Resampling.LANCZOS)
        profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        cover.save(folder/'cover.jpg',format='JPEG',quality=95,subsampling=0,icc_profile=profile)
