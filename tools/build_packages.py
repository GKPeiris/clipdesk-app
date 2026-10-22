#!/usr/bin/python3
"""Build distro-native packages without pip or downloading dependencies.

DEB uses the documented ar + tar format. RPM uses rpmbuild when installed;
RPM builds require the rpm-build package.
"""
import argparse
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION='1.1.0'
EPOCH=int(os.environ.get('SOURCE_DATE_EPOCH','1792627200'))


def copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)
    target.chmod(0o644)


def stage_tree(stage):
    if stage.exists(): shutil.rmtree(stage)
    app=stage/'usr/share/clipdeck'
    for source in sorted((ROOT/'clipdeck').glob('*.py')): copy(source,app/'clipdeck'/source.name)
    copy(ROOT/'run.py',app/'run.py')
    copy(ROOT/'launcher.py',app/'launcher.py')
    copy(ROOT/'data/clipdeck.service',stage/'usr/lib/systemd/user/clipdeck.service')
    copy(ROOT/'data/style.css',app/'data/style.css')
    binfile=stage/'usr/bin/clipdeck'; binfile.parent.mkdir(parents=True)
    binfile.write_text('#!/bin/sh\nexec /usr/bin/python3 /usr/share/clipdeck/launcher.py "$@"\n'); binfile.chmod(0o755)
    for source in ['README.md','LICENSE']:
        copy(ROOT/source,stage/'usr/share/doc/clipdeck'/source)
    copy(ROOT/'LICENSE',stage/'usr/share/doc/clipdeck/copyright')
    copy(ROOT/'data/io.github.clipdeck.ClipDeck.desktop',stage/'usr/share/applications/io.github.clipdeck.ClipDeck.desktop')
    copy(ROOT/'data/io.github.clipdeck.ClipDeck.service',stage/'usr/share/dbus-1/services/io.github.clipdeck.ClipDeck.service')
    copy(ROOT/'data/io.github.clipdeck.ClipDeck.svg',stage/'usr/share/icons/hicolor/scalable/apps/io.github.clipdeck.ClipDeck.svg')
    extension=stage/'usr/share/gnome-shell/extensions/clipdeck@local'
    for source in sorted((ROOT/'extension').rglob('*')):
        if source.is_file() and source.name!='gschemas.compiled': copy(source,extension/source.relative_to(ROOT/'extension'))
    subprocess.run(['glib-compile-schemas','--strict',str(extension/'schemas')],check=True)
    for path in stage.rglob('*'):
        if path.is_dir(): path.chmod(0o755)


def tar_bytes(directory):
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w:xz',format=tarfile.GNU_FORMAT) as archive:
        for path in sorted(directory.rglob('*')):
            info=archive.gettarinfo(str(path),arcname='./'+str(path.relative_to(directory)))
            info.uid=info.gid=0; info.uname=info.gname='root'; info.mtime=EPOCH
            if path.is_file():
                with path.open('rb') as f: archive.addfile(info,f)
            else: archive.addfile(info)
    return output.getvalue()


def ar_write(path,members):
    with path.open('wb') as f:
        f.write(b'!<arch>\n')
        for name,data in members:
            header=f'{name+"/":<16}{EPOCH:<12}{0:<6}{0:<6}{"100644":<8}{len(data):<10}`\n'
            assert len(header)==60
            f.write(header.encode('ascii')); f.write(data)
            if len(data)%2: f.write(b'\n')


def build_deb(stage,work,dist):
    control=work/'deb-control'; control.mkdir(exist_ok=True)
    size=sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())
    (control/'control').write_text(f'''Package: clipdeck
Version: {VERSION}-1
Section: utils
Priority: optional
Architecture: all
Maintainer: ClipDeck contributors <clipdeck@localhost>
Installed-Size: {(size+1023)//1024}
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0 (>= 4.8)
Suggests: gnome-shell (>= 45)
Description: Native clipboard history, snippets, images and emoji
 A local GTK 4 clipboard manager with search, pinned items, rich text,
 image and file references, export/import, and a GNOME companion extension.
''')
    md5=[]
    for p in sorted(stage.rglob('*')):
        if p.is_file(): md5.append(f'{hashlib.md5(p.read_bytes()).hexdigest()}  {p.relative_to(stage)}')
    (control/'md5sums').write_text('\n'.join(md5)+'\n')
    package=dist/f'clipdeck_{VERSION}-1_all.deb'
    ar_write(package,[('debian-binary',b'2.0\n'),('control.tar.xz',tar_bytes(control)),('data.tar.xz',tar_bytes(stage))])
    return package


def build_rpm(stage,work,dist):
    top=work/'rpm'
    for name in ['BUILD','BUILDROOT','SPECS','SOURCES','RPMS','SRPMS','tmp']: (top/name).mkdir(parents=True,exist_ok=True)
    source=top/'SOURCES'/f'clipdeck-{VERSION}.tar.gz'
    with tarfile.open(source,'w:gz') as archive: archive.add(stage,arcname=f'clipdeck-{VERSION}')
    spec=top/'SPECS/clipdeck.spec'
    spec.write_text(f'''Name: clipdeck
Version: {VERSION}
Release: 1
Summary: Native clipboard history, snippets, images and emoji
License: MIT
BuildArch: noarch
Source0: %{{name}}-%{{version}}.tar.gz
Requires: python3 >= 3.10
Requires: python3-gobject
Requires: gtk4 >= 4.8
Suggests: gnome-shell >= 45
AutoReqProv: no

%description
A local GTK 4 clipboard manager with searchable history, pinned items,
rich text, image and file references, emoji, import/export and a GNOME
companion extension for global shortcuts and background capture.

%prep
tar -xzf %{{SOURCE0}}
%define _buildsubdir %{{name}}-%{{version}}

%build

%install
mkdir -p %{{buildroot}}
cp -a %{{name}}-%{{version}}/usr %{{buildroot}}/

%check
test -f %{{buildroot}}/usr/share/clipdeck/run.py

%files
/usr/bin/clipdeck
/usr/lib/systemd/user/clipdeck.service
/usr/share/clipdeck
/usr/share/applications/io.github.clipdeck.ClipDeck.desktop
/usr/share/dbus-1/services/io.github.clipdeck.ClipDeck.service
/usr/share/icons/hicolor/scalable/apps/io.github.clipdeck.ClipDeck.svg
/usr/share/gnome-shell/extensions/clipdeck@local
%doc /usr/share/doc/clipdeck/README.md
%doc /usr/share/doc/clipdeck/copyright
%license /usr/share/doc/clipdeck/LICENSE
''')
    macros={'_tmppath':str(top/'tmp'),'_topdir':str(top),'_rpmdir':str(dist),'_rpmfilename':'%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}.rpm','_rpmformat':'4','_binary_payload':'w9.gzdio','__os_install_post':'%{nil}','__spec_install_post':'%{nil}','_build_id_links':'none'}
    if shutil.which('rpmbuild'):
        check_files=Path(shutil.which('rpmbuild')).resolve().parents[1]/'lib/rpm/check-files'
        if check_files.exists(): macros['__check_files']=str(check_files)
        command=['rpmbuild','-bb',str(spec)]
        for key,value in macros.items(): command.extend(['--define',key+' '+value])
        subprocess.run(command,check=True)
    else: raise RuntimeError('Install rpm-build, or use --deb-only on Ubuntu')
    copy(spec,dist/'clipdeck.spec')
    return dist/f'clipdeck-{VERSION}-1.noarch.rpm'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dist',type=Path,default=ROOT.parent)
    parser.add_argument('--work',type=Path,default=ROOT/'build')
    parser.add_argument('--deb-only',action='store_true')
    args=parser.parse_args()
    dist=args.dist.resolve(); work=args.work.resolve()
    dist.mkdir(parents=True,exist_ok=True); work.mkdir(parents=True,exist_ok=True)
    stage=work/'stage'; stage_tree(stage)
    packages=[build_deb(stage,work,dist)]
    if not args.deb_only: packages.append(build_rpm(stage,work,dist))
    extension=stage/'usr/share/gnome-shell/extensions/clipdeck@local'
    with zipfile.ZipFile(dist/'clipdeck-companion.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(extension.rglob('*')):
            if p.is_file(): archive.write(p,p.relative_to(extension))
    packages.append(dist/'clipdeck-companion.zip')
    archive_path=dist/f'clipdeck-{VERSION}-source.tar.gz'
    with tarfile.open(archive_path,'w:gz') as archive:
        for p in sorted(ROOT.rglob('*')):
            rel=p.relative_to(ROOT)
            if any(part in {'build','__pycache__','.git'} for part in rel.parts) or p.suffix=='.pyc': continue
            if p.is_file(): archive.add(p,arcname=f'clipdeck-{VERSION}/'+str(rel),recursive=False)
    packages.append(archive_path)
    (dist/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in packages))
    for p in packages: print(f'BUILT {p} ({p.stat().st_size:,} bytes)')

if __name__=='__main__': main()
