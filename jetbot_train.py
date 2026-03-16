#!/usr/bin/env python3
"""Train ResNet18 for collision avoidance on JetBot.

Usage: python3 jetbot_train.py [--epochs 10] [--dataset /home/jetbot/dataset_v2]
"""
import os
import sys
import time
import glob
import random
import argparse
import cv2
import numpy as np

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

try:
    from PIL import Image as PILImage
    HAS_PIL = True
except:
    HAS_PIL = False

DATASET_DIR = '/home/jetbot/dataset_v2'
MODEL_OUT = '/home/jetbot/best_model_resnet18_v2.pth'


# ---- ResNet18 (no torchvision dependency) ----

class BasicBlock(nn.Module):
    expansion = 1
    def __init__(self, in_ch, out_ch, stride=1, downsample=None):
        super(BasicBlock, self).__init__()
        self.conv1 = nn.Conv2d(in_ch, out_ch, 3, stride, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(out_ch)
        self.conv2 = nn.Conv2d(out_ch, out_ch, 3, 1, 1, bias=False)
        self.bn2 = nn.BatchNorm2d(out_ch)
        self.downsample = downsample

    def forward(self, x):
        identity = x
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        if self.downsample is not None:
            identity = self.downsample(x)
        out += identity
        return F.relu(out)


class ResNet18(nn.Module):
    def __init__(self, num_classes=2):
        super(ResNet18, self).__init__()
        self.in_ch = 64
        self.conv1 = nn.Conv2d(3, 64, 7, 2, 3, bias=False)
        self.bn1 = nn.BatchNorm2d(64)
        self.maxpool = nn.MaxPool2d(3, 2, 1)
        self.layer1 = self._make_layer(64, 2)
        self.layer2 = self._make_layer(128, 2, stride=2)
        self.layer3 = self._make_layer(256, 2, stride=2)
        self.layer4 = self._make_layer(512, 2, stride=2)
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.fc = nn.Linear(512, num_classes)

    def _make_layer(self, out_ch, blocks, stride=1):
        downsample = None
        if stride != 1 or self.in_ch != out_ch:
            downsample = nn.Sequential(
                nn.Conv2d(self.in_ch, out_ch, 1, stride, bias=False),
                nn.BatchNorm2d(out_ch),
            )
        layers = [BasicBlock(self.in_ch, out_ch, stride, downsample)]
        self.in_ch = out_ch
        for _ in range(1, blocks):
            layers.append(BasicBlock(out_ch, out_ch))
        return nn.Sequential(*layers)

    def forward(self, x):
        x = self.maxpool(F.relu(self.bn1(self.conv1(x))))
        x = self.layer4(self.layer3(self.layer2(self.layer1(x))))
        x = self.avgpool(x)
        x = torch.flatten(x, 1)
        return self.fc(x)


# ---- Dataset ----

class CollisionDataset(Dataset):
    """Load free/blocked images from directory structure."""
    
    def __init__(self, root, split='train', train_ratio=0.8):
        self.mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        self.std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        
        # Collect all images
        free_imgs = sorted(glob.glob(os.path.join(root, 'free', '*.jpg')))
        blocked_imgs = sorted(glob.glob(os.path.join(root, 'blocked', '*.jpg')))
        
        # Shuffle deterministically
        random.seed(42)
        random.shuffle(free_imgs)
        random.shuffle(blocked_imgs)
        
        # Split
        nf = int(len(free_imgs) * train_ratio)
        nb = int(len(blocked_imgs) * train_ratio)
        
        if split == 'train':
            self.images = [(f, 0) for f in free_imgs[:nf]] + [(f, 1) for f in blocked_imgs[:nb]]
        else:
            self.images = [(f, 0) for f in free_imgs[nf:]] + [(f, 1) for f in blocked_imgs[nb:]]
        
        random.shuffle(self.images)
        print("[Dataset] {} split: {} images (free={}, blocked={})".format(
            split, len(self.images),
            sum(1 for _, l in self.images if l == 0),
            sum(1 for _, l in self.images if l == 1)))
    
    def __len__(self):
        return len(self.images)
    
    def __getitem__(self, idx):
        path, label = self.images[idx]
        # Load and preprocess
        img = cv2.imread(path)
        if img is None:
            # Return black image on error
            img = np.zeros((224, 224, 3), dtype=np.uint8)
        img = cv2.resize(img, (224, 224))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        # Random augmentation for training
        if random.random() > 0.5:
            img = cv2.flip(img, 1)  # Horizontal flip
        
        # Normalize
        img = img.astype(np.float32) / 255.0
        img = (img - self.mean) / self.std
        img = img.transpose(2, 0, 1)  # HWC -> CHW
        
        return torch.from_numpy(img), label


def train(args):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print("[Train] Device: {}".format(device))
    
    # Dataset
    train_ds = CollisionDataset(args.dataset, 'train')
    val_ds = CollisionDataset(args.dataset, 'val')
    
    if len(train_ds) == 0:
        print("[Train] ERROR: No training images! Collect data first.")
        sys.exit(1)
    
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)
    
    # Model - start from pre-trained if available
    model = ResNet18(num_classes=2)
    
    pretrained_path = '/home/jetbot/jetbot/notebooks/collision_avoidance/best_model_resnet18.pth'
    if os.path.exists(pretrained_path) and not args.scratch:
        print("[Train] Loading pre-trained weights from {}".format(pretrained_path))
        state = torch.load(pretrained_path, map_location='cpu')
        model.load_state_dict(state)
    else:
        print("[Train] Training from scratch")
    
    model = model.to(device)
    
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=5, gamma=0.5)
    criterion = nn.CrossEntropyLoss()
    
    best_acc = 0.0
    
    for epoch in range(args.epochs):
        # Train
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0
        
        t0 = time.time()
        for images, labels in train_loader:
            images = images.to(device)
            labels = labels.to(device)
            
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item() * images.size(0)
            _, predicted = outputs.max(1)
            train_total += labels.size(0)
            train_correct += predicted.eq(labels).sum().item()
        
        train_acc = 100.0 * train_correct / max(train_total, 1)
        train_loss /= max(train_total, 1)
        
        # Validate
        model.eval()
        val_correct = 0
        val_total = 0
        
        with torch.no_grad():
            for images, labels in val_loader:
                images = images.to(device)
                labels = labels.to(device)
                outputs = model(images)
                _, predicted = outputs.max(1)
                val_total += labels.size(0)
                val_correct += predicted.eq(labels).sum().item()
        
        val_acc = 100.0 * val_correct / max(val_total, 1)
        elapsed = time.time() - t0
        
        print("[Epoch {}/{}] loss={:.4f} train_acc={:.1f}% val_acc={:.1f}% ({:.1f}s)".format(
            epoch + 1, args.epochs, train_loss, train_acc, val_acc, elapsed))
        
        # Save best
        if val_acc >= best_acc:
            best_acc = val_acc
            torch.save(model.state_dict(), args.output)
            print("  -> Saved best model (val_acc={:.1f}%)".format(val_acc))
        
        scheduler.step()
    
    print("\n[Train] Done! Best val_acc={:.1f}%".format(best_acc))
    print("[Train] Model saved to {}".format(args.output))
    
    c = count_dataset(args.dataset)
    print("[Train] Dataset: free={}, blocked={}".format(c['free'], c['blocked']))


def count_dataset(root):
    counts = {}
    for label in ['free', 'blocked']:
        d = os.path.join(root, label)
        if os.path.exists(d):
            counts[label] = len([f for f in os.listdir(d) if f.endswith('.jpg')])
        else:
            counts[label] = 0
    return counts


def main():
    parser = argparse.ArgumentParser(description='Train collision avoidance model')
    parser.add_argument('--dataset', default=DATASET_DIR, help='Dataset directory')
    parser.add_argument('--output', default=MODEL_OUT, help='Output model path')
    parser.add_argument('--epochs', type=int, default=10, help='Training epochs')
    parser.add_argument('--batch-size', type=int, default=8, help='Batch size')
    parser.add_argument('--lr', type=float, default=0.001, help='Learning rate')
    parser.add_argument('--scratch', action='store_true', help='Train from scratch (no pretrained)')
    args = parser.parse_args()
    
    train(args)


if __name__ == '__main__':
    main()
