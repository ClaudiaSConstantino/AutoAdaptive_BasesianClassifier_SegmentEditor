import os
import vtk, qt, ctk, slicer
import logging
from SegmentEditorEffects import *
from slicer.ScriptedLoadableModule import *
# Import system modules
import sys, string, os, subprocess
import SimpleITK as sitk
import sitkUtils


class BayesianSegAut_SegmentEditor(ScriptedLoadableModule):
  """
  This class is the 'hook' for slicer to detect and recognize the extension
  as a loadable scripted module
  """
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Self-Adaptive Bayesian Segmentation Tool"
    self.parent.categories = ["Developer Tools.Segment Editor Extensions"]
    self.parent.dependencies = ['Terminologies']
    self.parent.contributors = ["Cláudia S. Constantino (Champalimaud Centre for the Unknown, Champalimaud Foundation)",
                               "Francisco P. M. Oliveira (Champalimaud Centre for the Unknown, Champalimaud Foundation)"] # insert your name in the list
    self.parent.hidden = True

    self.parent.helpText = """ This hidden module registers the segment editor effect.
    This is a scripted loadable extension for self-adaptive segmentation using a bayesian-based algorithm for whole-body PET images.
    """
    self.parent.acknowledgementText ="""
    This editor extension was developed by Cláudia S. Constantino and Francisco P. M. Oliveira of 
    Champalimaud Centre for the Unknown, Champalimaud Foundation, and was 
    partially funded by grant LISBOA-01-0247-FEDER-039885."""  # replace with organization, grant and thanks.

    #self.parent = parent


    slicer.app.connect("startupCompleted()", self.registerEditorEffect)

  def registerEditorEffect(self):
    import qSlicerSegmentationsEditorEffectsPythonQt as effects
    scriptedEffect = effects.qSlicerSegmentEditorScriptedEffect(None)
    scriptedEffect.setPythonSource(__file__.replace('\\','/'))
    scriptedEffect.self().register()



class BayesianSegAut_SegmentEditorEffect(AbstractScriptedSegmentEditorEffect):
  """ BayesianSegAut is an Effect that implements the
      Self-Adaptive Bayesian Segmentation in segment editor
  """

  scene = slicer.vtkMRMLScene()
  #vtkSegmentationLogic = None  # note: The necessary C++ module might not have been loaded yet.


  def __init__(self, scriptedEffect):
    scriptedEffect.name = 'Self-Adaptive Bayesian Segmentation'
    # Indicates that effect does not operate on one segment, but the whole segmentation.
    # This means that while this effect is active, no segment can be selected
    #scriptedEffect.perSegment = False
    AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)
    #self.scriptedEffect = scriptedEffect


    # Observation for auto-update
    self.observedSegmentation = None
    self.segmentationNodeObserverTags = []

    # undo/redo helpers
    self.scene.SetUndoOn()
    self.segmentationIdCounter = 0

    #self.active = False
    #self.debug = False


  def clone(self):
    import qSlicerSegmentationsEditorEffectsPythonQt as effects
    clonedEffect = effects.qSlicerSegmentEditorScriptedEffect(None)
    clonedEffect.setPythonSource(__file__.replace('\\', '/'))
    return clonedEffect


  def icon(self):
    iconPath = os.path.join(os.path.dirname(__file__), 'BayesianSegAut_SegmentEditor.png')
    if os.path.exists(iconPath):
      return qt.QIcon(iconPath)
    return qt.QIcon()


  def helpText(self):
    return """<html>Scripted loadable extension for self-adaptive segmentation using a bayesian-based algorithm for whole-body PET images<br>. Instructions:
            <p><ul>
            <li> Start by drawing a large 3D region of interest (ROI) around the lesion, ensuring the whole lesion/organ and also the surrounding background 
            is included. </li>
            <li> Choose if the segmentation is to be performed at all segments previously drawn or just in the current working segment and then, select Apply button. </li>
            <li> The complete segmentation will be created with a Self-Adaptive configuration of a Bayesian-based segmentation classifier. <\li>
            </ul><p>
            </html>"""


  def setupOptionsFrame(self):
    operationLayout = qt.QVBoxLayout()

    self.oneLabelRadioButton = qt.QRadioButton("Current segment")
    self.oneLabelRadioButton.setToolTip("Segment within the current selected segment ID.")
    self.allLabelsRadioButton = qt.QRadioButton("All segments")
    self.allLabelsRadioButton.setToolTip("Segmentation will be performed within all segments previously drawn.")
    operationLayout.addWidget(self.oneLabelRadioButton)
    operationLayout.addWidget(self.allLabelsRadioButton)
    self.oneLabelRadioButton.setChecked(True)

    self.scriptedEffect.addLabeledOptionsWidget("Segmentation: ", operationLayout)

    # Apply button
    self.segButton = qt.QPushButton("APPLY")
    self.segButton.toolTip = "Run the Bayesian segmentation algorithm."
    self.segButton.connect('clicked(bool)', self.onApply)
    self.scriptedEffect.addOptionsWidget(self.segButton)



  def createCursor(self, widget):
      # Turn off effect-specific cursor for this effect
      return slicer.util.mainWindow().cursor

  def setMRMLDefaults(self):
    self.scriptedEffect.setParameterDefault("SegmentationId", 0)

  def updateGUIFromMRML(self):
    self.updatingGUI = True

  def updateMRMLFromGUI(self):
    if self.updatingGUI:
      return
    segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
    disableState = segmentationNode.GetDisableModifiedEvent()
    segmentationNode.SetDisableModifiedEvent(1)

    segmentationNode.SetDisableModifiedEvent(disableState)
    if not disableState:
      segmentationNode.InvokePendingModifiedEvent()

  def reset(self):
    self.scene.Clear(True)
    self.segmentationIdCounter = 0

    # clear PETTumorSegmentation.SegmentationId in all segments
    paramsNode = self.scriptedEffect.parameterSetNode()
    segmentation = paramsNode.GetSegmentationNode().GetSegmentation()
    segmentIDs = vtk.vtkStringArray()
    segmentation.GetSegmentIDs(segmentIDs)
    for index in range(segmentIDs.GetNumberOfValues()):
      segmentID = segmentIDs.GetValue(index)
      segment = segmentation.GetSegment(segmentID)

  def onSegmentationModified(self, caller, event):
    if not self.active:
      self.reset()

  def observeSegmentation(self, observationEnabled):
    import vtkSegmentationCorePython as vtkSegmentationCore
    segmentation = self.scriptedEffect.parameterSetNode().GetSegmentationNode().GetSegmentation()
    if observationEnabled and self.observedSegmentation == segmentation:
      return
    if not observationEnabled and not self.observedSegmentation:
      return
    # Need to update the observer
    # Remove old observer
    if self.observedSegmentation:
      for tag in self.segmentationNodeObserverTags:
        self.observedSegmentation.RemoveObserver(tag)
      self.segmentationNodeObserverTags = []
      self.observedSegmentation = None
    # Add new observer
    if observationEnabled and segmentation is not None:
      self.observedSegmentation = segmentation
      observedEvents = [
        vtkSegmentationCore.vtkSegmentation.SegmentAdded,
        vtkSegmentationCore.vtkSegmentation.SegmentRemoved,
        vtkSegmentationCore.vtkSegmentation.SegmentModified]
      for eventId in observedEvents:
        self.segmentationNodeObserverTags.append(self.observedSegmentation.AddObserver(eventId, self.onSegmentationModified))

  def activate(self):
    self.active = True
    self.reset()
    self.observeSegmentation(True)

  def deactivate(self):
    self.active = False
    self.reset()
    self.observeSegmentation(False)

  def saveStateForUndo(self):
    self.scriptedEffect.saveStateForUndo()
    self.scene.SaveStateForUndo()

  # Applies from the button.  Due to lack of center point, this must be certain that the tool
  # was previously used so that a center point is available.
  def onApply(self):
    # do not apply if no previous use of the tool to update settings for

    # Activate Undo/Redo functions
    self.saveStateForUndo()
    self.updateMRMLFromGUI()

    paramsNode = self.scriptedEffect.parameterSetNode()

    #Get volume node
    masterVolumeNode = paramsNode.GetMasterVolumeNode()
    #print(masterVolumeNode)

    segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
    #print(segmentationNode)
    visibleSegmentIds = vtk.vtkStringArray()
    segmentationNode.GetSegmentation().GetSegmentIDs(visibleSegmentIds)

    # Generate merged labelmap of all visible segments, as the filter expects a single labelmap with all the labels.
    mergedLabelmapNode = slicer.vtkMRMLLabelMapVolumeNode()
    slicer.mrmlScene.AddNode(mergedLabelmapNode)
    slicer.vtkSlicerSegmentationsModuleLogic.ExportSegmentsToLabelmapNode(segmentationNode, visibleSegmentIds,
                                                                          mergedLabelmapNode, masterVolumeNode)
    #print(mergedLabelmapNode)

    if (self.oneLabelRadioButton.isChecked()):
      selectedSegmentID = paramsNode.GetSelectedSegmentID()
      labelNumber = selectedSegmentID[-1]

    if (self.allLabelsRadioButton.isChecked()):
      labelNumber = "0"

    # print(inputVolume)
    # print(inputMaskVolume)
    print(labelNumber)

    # Get current working directory
    # currentDir = os.getcwd() #Get slicer directory, i.e., where the slicer pyhton console directory is.
    dir_path = os.path.dirname(os.path.realpath(__file__))

    # Defining the directory of the different files further needed
    executableDir = os.path.join(dir_path, "bin\\BayesianSegAut_Editor.exe")
    imageFileName = os.path.join(dir_path, "image.nrrd")
    maskFileName = os.path.join(dir_path, "mask.nrrd")
    outputMaskFileName = os.path.join(dir_path, "outputMask.nrrd")

    # Save the image and mask (vtkMRMLScalarVolumeNode and vtkMRMLLabelMapVolumeNode) to a NIFTI file to be loaded by the executable code C++
    slicer.util.saveNode(masterVolumeNode, imageFileName)
    slicer.util.saveNode(mergedLabelmapNode, maskFileName)

    # Running an outside program (executable) -> 1. Executable dir; 2. Input image; 3. Input Mask; 4. Output name image; 5. label number
    DETACHED_PROCESS = 0x00000008  # force to have no console at all
    outputSegmentation = subprocess.Popen(
      [executableDir] + [imageFileName] + [maskFileName] + [outputMaskFileName] + [labelNumber],
      creationflags=DETACHED_PROCESS)
    outputSegmentation.wait()

    # Load volume outputted by executable
    loadedOutputVolume = slicer.util.loadLabelVolume(outputMaskFileName, properties={'show': False})
    #inputMaskVolume.SetAndObserveImageData(loadedOutputVolume.GetImageData())
    # Update segmentation from labelmap node and remove temporary nodes
    slicer.vtkSlicerSegmentationsModuleLogic.ImportLabelmapToSegmentationNode(loadedOutputVolume, segmentationNode,
                                                                              visibleSegmentIds)

    slicer.mrmlScene.RemoveNode(mergedLabelmapNode) #remove both label map volumes. Not needed
    slicer.mrmlScene.RemoveNode(loadedOutputVolume)

    # Delete de files created to use in the executable
    os.remove(imageFileName)
    os.remove(maskFileName)
    os.remove(outputMaskFileName)