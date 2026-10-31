"""Content errors and complete DIY workflows in disposable project copies."""
from pathlib import Path
import unittest,tempfile,shutil,sys,json,contextlib,io,zipfile
import subprocess
import importlib.util

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from model import load,read,write,sha,compile_content
from build import build
from project import main,release_audit
from media import run,executable,probe,transcode,pictures

def clone(target):
    for folder in ['src','content','tools','docs','tests']:
        shutil.copytree(ROOT/folder,target/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for p in ROOT.iterdir():
        if p.is_file() and p.name not in ['Thumbs.db']: shutil.copy2(p,target/p.name)

class ContractTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'.qa').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='contracts-',dir=ROOT/'.qa');self.root=Path(self.temp.name);clone(self.root)
        self.p,self.g,self.s,self.d,_=load(self.root)
        self.id=next(iter(self.s));self.file=self.root/'content/looks'/self.id/'look.json'
    def tearDown(self): self.temp.cleanup()
    def invalid(self,change,filename=None):
        path=filename or self.file;value=read(path);change(value);write(path,value)
        with self.assertRaises(ValueError):load(self.root)
    def test_path_escape(self): self.invalid(lambda x:x.update(video='../../project.json'))
    def test_invalid_freeze(self): self.invalid(lambda x:x.update(freeze=x['duration']+1))
    def test_pair_requires_held(self): self.invalid(lambda x:x['entries'][0].pop('held'),self.file.parent/'dialogue.json')
    def test_duplicate_line_ids(self):
        self.invalid(lambda x:x['restored'][0].update(id=x['entries'][0]['id']),self.file.parent/'dialogue.json')
    def test_wrong_wardrobe(self):self.invalid(lambda x:x.update(wardrobe='missing'))
    def test_duplicate_host_value(self):
        other=next((v for k,v in self.s.items() if k!=self.id),None)
        if other:self.invalid(lambda x:x.update(hostValue=other['hostValue']))
    def test_missing_asset(self): self.invalid(lambda x:x.update(video='missing.webm'))
    def test_invalid_loop(self):
        id=next((id for id,s in self.s.items() if s['kind']=='companion'),None)
        if id:self.invalid(lambda x:x.update(loopEnd=x['loopStart']),self.root/'content/looks'/id/'look.json')
    def test_disabled_dialogue_is_explicit(self):
        write(self.file.parent/'dialogue.json',{'enabled':False});data=compile_content(self.root)[-1]
        look=next(x for x in data['PURPLE_LOOKS'] if x['id']==self.id)
        self.assertTrue(look['silent']);self.assertEqual(look['dialogue']['enter'],[''])
    def test_build_whitelist_and_metadata(self):
        (self.file.parent/'unreferenced-secret.txt').write_text('not runtime',encoding='utf-8')
        for host in ['wallpaper-engine','lively']:
            folder,manifest=build(self.root,host)
            self.assertFalse(any('secret' in x or 'look-04' in x for x in manifest))
            self.assertEqual(len([x for x in manifest if x.endswith('.webm')]),sum(1+len(s['qualities']) for s in self.s.values()))
            if host=='wallpaper-engine': self.assertNotIn('workshopid',read(folder/'project.json'))
            else:self.assertEqual(read(folder/'LivelyInfo.json')['Arguments'],'--pause-event true')
            self.assertTrue((folder/'LICENSE').exists())
            build(self.root,host) # rebuild replaces only its own marked generated folder
    def test_demo_is_not_publishable(self):
        if self.p.get('sample'):
            with self.assertRaisesRegex(ValueError,'Publish audit failed'):release_audit(self.root)

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe') and importlib.util.find_spec('PIL'),'FFmpeg and Pillow required for integration workflow')
class WorkflowTests(unittest.TestCase):
    def test_untagged_source_gets_bt709_tags(self):
        # 新版 FFmpeg 不再可靠地应用 -color_trc 等输出参数；无标签源片也必须得到完整 BT.709 标签并能截图
        (ROOT/'.qa').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='color-tags-',dir=ROOT/'.qa') as temp:
            folder=Path(temp);source=folder/'untagged.mp4';keys=['colorSpace','colorRange','colorTransfer','colorPrimaries']
            run([executable('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=c=blue:s=320x180:r=60:d=1','-c:v','libx264','-pix_fmt','yuv420p',str(source)])
            self.assertEqual([probe(source)[k] for k in keys],[None]*4)
            self.assertEqual([transcode(source,folder/'video.webm')[k] for k in keys],['bt709','tv','bt709','bt709'])
            pictures(folder/'video.webm',folder,.5)
    def test_clean_copy_full_diy_workflow(self):
        (ROOT/'.qa').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='全新目录 空格-',dir=ROOT/'.qa') as temp:
            parent=Path(temp);root=parent/'我的壁纸';root.mkdir();clone(root)
            inputs=parent/'原片';inputs.mkdir();source=inputs/'sample one.mp4';second=inputs/'sample two.mp4'
            for path,duration,color in [(source,2,'blue'),(second,2.5,'purple')]:
                run([executable('ffmpeg'),'-v','error','-y','-f','lavfi','-i',f'color=c={color}:s=320x180:r=60:d={duration}','-c:v','libx264','-pix_fmt','yuv420p',str(path)])
            before={str(x):sha(x) for x in inputs.iterdir()}
            def call(*args):
                with contextlib.redirect_stdout(io.StringIO()):return main(['--root',str(root),*args])
            initial=load(root);group=initial[1][0]['id'];old_ids=set(initial[2])
            build(root)
            call('init','--id','qa-my-wallpaper','--title','我自己的壁纸','--author','测试作者','--apply')
            plan=call('add','--id','qa-new','--name','新内容','--wardrobe',group,'--kind','companion','--source',str(source),'--loop-start','.5')
            self.assertFalse(plan['apply']);self.assertEqual(set(load(root)[2]),old_ids)
            call('add','--id','qa-new','--name','新内容','--wardrobe',group,'--kind','companion','--source',str(source),'--loop-start','.5','--apply')
            item=load(root)[2]['qa-new'];host=item['hostValue'];self.assertEqual(len(load(root)[2]),len(old_ids)+1)
            self.assertEqual(item['width'],320);self.assertEqual(item['height'],180)
            build(root);call('check','--media')
            script={'enabled':True,'entries':[{'id':'entry-1','enter':'这是独立测试的入场句。','held':'这是独立测试的接话句。'}],
                **{k:[{'id':k+'-1','text':'独立验证文本：'+k}] for k in ['continuous','restored','random','affection']}}
            dialogue_file=parent/'我的对白.json';write(dialogue_file,script)
            call('dialogue','--id','qa-new','--file',str(dialogue_file),'--apply')
            call('replace','--id','qa-new','--source',str(second),'--loop-start','.6','--apply')
            self.assertEqual(load(root)[2]['qa-new']['hostValue'],host);self.assertEqual(load(root)[3]['qa-new'],script)
            call('quality','--id','qa-new','--source',str(second),'--height','1080','--apply')
            self.assertIn('1080p',load(root)[2]['qa-new']['qualities']);call('check','--media')
            # Every original sample can be removed without retaining hidden catalog slots.
            for id in old_ids:call('remove','--id',id,'--apply')
            self.assertEqual(set(load(root)[2]),{'qa-new'})
            p,groups,_,_,shared=load(root);p['sample']=False;write(root/'content/project.json',p)
            background=root/'content/backgrounds/my-background.jpg';shutil.copy2(root/'content/looks/qa-new/still.jpg',background)
            groups[0]['background']='content/backgrounds/my-background.jpg';write(root/'content/wardrobes.json',groups)
            for key in shared['replies']:shared['replies'][key]=['本地测试回应：'+key]
            for key in shared['fixed']:shared['fixed'][key]='本地测试状态：'+key
            write(root/'content/shared-dialogue.json',shared);release_audit(root)
            for host_name in ['wallpaper-engine','lively']:
                report=call('pack','--host',host_name)
                with zipfile.ZipFile(report['archive']) as z:
                    self.assertIsNone(z.testzip());self.assertTrue(all(not x.startswith(('.qa','.history','content','tools')) for x in z.namelist()))
                    self.assertFalse(any(any(id in x for id in old_ids) for x in z.namelist()))
                    self.assertIn('media/look-qa-new.webm',z.namelist())
            (root/'private.json').write_text('secret',encoding='utf-8')
            (root/'content/unused-original.mp4').write_bytes(b'not an asset')
            report=call('source');clean=parent/'再解压 独立源码';clean.mkdir()
            with zipfile.ZipFile(report['archive']) as z:
                self.assertNotIn('private.json',z.namelist());self.assertNotIn('content/unused-original.mp4',z.namelist());z.extractall(clean)
            # Launch the extracted tool itself, so imports cannot fall back to this checkout.
            subprocess.run([sys.executable,'-X','utf8','tools/project.py','build','--host','both'],cwd=clean,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            subprocess.run([sys.executable,'-X','utf8','tools/project.py','check','--media'],cwd=clean,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            load(clean)
            self.assertEqual(before,{str(x):sha(x) for x in inputs.iterdir()})
            self.assertTrue((root/'.history').is_dir())

if __name__=='__main__':unittest.main()
